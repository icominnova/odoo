# -*- coding: utf-8 -*-
import json
import logging
import os
import shutil
import subprocess
import tarfile
import tempfile
import time
import zipfile
from contextlib import closing
from datetime import datetime

import psycopg2
import requests
from psycopg2 import sql

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.misc import find_pg_tool
from odoo.addons.odoo_saas_kit.models.lib import containers

_logger = logging.getLogger(__name__)


class SaasBackupMigration(models.Model):
    _name = 'saas.backup.migration'
    _description = 'Migration de sauvegarde vers client SaaS'
    _order = 'id desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    _POST_RESTORE_UPGRADE_MODULES = (
        'muk_web_theme',
    )

    name = fields.Char(string='Migration', readonly=True, copy=False)
    backup_file_id = fields.Many2one('saas.backup.file', string='Sauvegarde', required=True, readonly=True, ondelete='restrict')
    client_id = fields.Many2one('saas.client', string='Client SaaS cible', tracking=True, ondelete='restrict')
    contract_id = fields.Many2one(related='client_id.saas_contract_id', string='Contrat', readonly=True)
    target_database = fields.Char(related='client_id.database_name', string='Base cible', readonly=True)
    target_url = fields.Char(related='client_id.client_url', string='URL cible', readonly=True)
    client_state = fields.Selection(related='client_id.state', string='État client', readonly=True)
    state = fields.Selection([
        ('draft', 'Brouillon'),
        ('blocked', 'Bloquée'),
        ('analyzed', 'Prête'),
        ('running', 'Migration en cours'),
        ('validation', 'À valider'),
        ('done', 'Finalisée'),
        ('failed', 'Échec'),
    ], string='État', default='draft', tracking=True, readonly=True)
    sync_contract_modules = fields.Boolean(string='Synchroniser les modules existants du catalogue avec le contrat', default=True)
    confirm_migration = fields.Boolean(string='Je confirme la restauration destructive de la base cible')
    backup_module_count = fields.Integer(string='Modules du backup', readonly=True)
    runtime_available_count = fields.Integer(string='Disponibles dans le runtime', readonly=True)
    runtime_missing_count = fields.Integer(string='Modules runtime manquants', readonly=True)
    runtime_missing_modules = fields.Text(string='Modules runtime manquants', readonly=True)
    catalog_match_count = fields.Integer(string='Modules trouvés dans le catalogue SaaS', readonly=True)
    contract_added_count = fields.Integer(string='Modules ajoutés au contrat', readonly=True)
    analysis_report = fields.Text(string="Rapport d'analyse", readonly=True)
    snapshot_db_path = fields.Char(string='Snapshot DB avant migration', readonly=True)
    snapshot_filestore_path = fields.Char(string='Snapshot filestore avant migration', readonly=True)
    cron_ids_json = fields.Text(string='Crons actifs historiques', readonly=True)
    smtp_ids_json = fields.Text(string='Serveurs SMTP actifs historiques', readonly=True)
    http_status = fields.Integer(string='HTTP après restauration', readonly=True)
    error_message = fields.Text(string='Erreur', readonly=True)
    operation_log = fields.Text(string='Journal', readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name'):
                vals['name'] = 'MIG-%s' % datetime.now().strftime('%Y%m%d-%H%M%S')
        return super().create(vals_list)

    @api.onchange('client_id')
    def _onchange_client_id(self):
        self.state = 'draft'
        self.runtime_available_count = 0
        self.runtime_missing_count = 0
        self.runtime_missing_modules = False
        self.catalog_match_count = 0
        self.analysis_report = False
        self.confirm_migration = False

    def _require_admin(self):
        if not self.env.user.has_group('base.group_system'):
            raise UserError(_('Accès réservé aux administrateurs système.'))

    def _append_log(self, message):
        self.ensure_one()
        stamp = fields.Datetime.now()
        line = '[%s] %s' % (stamp, message)
        self.operation_log = '%s%s%s' % (self.operation_log or '', '\n' if self.operation_log else '', line)

    def _server_context(self):
        self.ensure_one()
        if not self.client_id or not self.client_id.server_id:
            raise UserError(_('Sélectionnez un client SaaS cible valide.'))
        host_server, db_server = self.client_id.server_id.get_server_details()
        if host_server.get('server_type') != 'self':
            raise UserError(_('Cette première version automatise uniquement les clients hébergés sur le serveur SaaS local.'))
        return host_server, db_server

    def _pg_connect(self, database_name, db_server):
        return psycopg2.connect(
            dbname=database_name,
            host=db_server.get('host') or '127.0.0.1',
            port=db_server.get('port') or 5432,
            user=db_server.get('user'),
            password=db_server.get('password'),
            connect_timeout=10,
        )

    def _pg_env(self, db_server):
        env = os.environ.copy()
        if db_server.get('host'):
            env['PGHOST'] = str(db_server['host'])
        if db_server.get('port'):
            env['PGPORT'] = str(db_server['port'])
        if db_server.get('user'):
            env['PGUSER'] = str(db_server['user'])
        if db_server.get('password'):
            env['PGPASSWORD'] = str(db_server['password'])
        return env

    def _backup_modules(self):
        self.ensure_one()
        return self.backup_file_id._manifest_modules()

    def action_analyze_target(self):
        self.ensure_one()
        self._require_admin()
        backup = self.backup_file_id
        if backup.analysis_state != 'valid':
            backup._analyze_backup_zip()
        if backup.analysis_state != 'valid':
            raise UserError(backup.analysis_message or _('La sauvegarde est invalide.'))
        if not self.client_id:
            raise UserError(_('Sélectionnez le client SaaS cible.'))
        if self.client_id.state not in ('started', 'stopped'):
            raise UserError(_('Le client SaaS cible doit être provisionné et dans l’état Démarré ou Arrêté.'))
        if not self.client_id.database_name:
            raise UserError(_('Le client cible ne possède pas de base de données.'))

        _host_server, db_server = self._server_context()
        modules = self._backup_modules()
        try:
            with closing(self._pg_connect(self.client_id.database_name, db_server)) as connection:
                with closing(connection.cursor()) as cursor:
                    cursor.execute('SELECT name FROM ir_module_module')
                    runtime_modules = {row[0] for row in cursor.fetchall()}
        except Exception as error:
            raise UserError(_('Impossible de lire le catalogue des modules de la base cible : %s') % error)

        missing = sorted(set(modules) - runtime_modules)
        catalog_modules = self.env['saas.module'].sudo().search([
            ('technical_name', 'in', modules),
            ('active', '=', True),
        ]) if modules else self.env['saas.module']
        report = _(
            'Backup : %(total)s module(s)\nRuntime cible : %(available)s disponible(s)\nManquants runtime : %(missing)s\nCatalogue SaaS correspondant : %(catalog)s',
            total=len(modules),
            available=len(set(modules) & runtime_modules),
            missing=len(missing),
            catalog=len(catalog_modules),
        )
        if missing:
            report += '\n\n' + _('RESTAURATION BLOQUÉE. Modules runtime manquants :\n%s') % '\n'.join(missing)

        self.write({
            'backup_module_count': len(modules),
            'runtime_available_count': len(set(modules) & runtime_modules),
            'runtime_missing_count': len(missing),
            'runtime_missing_modules': '\n'.join(missing),
            'catalog_match_count': len(catalog_modules),
            'analysis_report': report,
            'state': 'blocked' if missing else 'analyzed',
            'error_message': False,
        })
        return True

    def action_sync_contract_modules(self):
        self.ensure_one()
        self._require_admin()
        if not self.client_id or not self.contract_id:
            raise UserError(_('Sélectionnez d’abord le client SaaS cible.'))
        modules = self._backup_modules()
        catalog_modules = self.env['saas.module'].sudo().search([
            ('technical_name', 'in', modules),
            ('active', '=', True),
        ]) if modules else self.env['saas.module']
        existing_ids = set(self.contract_id.saas_module_ids.ids)
        to_add = catalog_modules.filtered(lambda module: module.id not in existing_ids)
        if to_add:
            self.contract_id.sudo().write({
                'saas_module_ids': [(4, module.id) for module in to_add],
            })
        if 'missed_modules' in self.client_id._fields:
            self.client_id.sudo().write({'missed_modules': False})
        self.contract_added_count = len(to_add)
        self._append_log(_('Modules du catalogue ajoutés au contrat : %s') % len(to_add))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Synchronisation terminée'),
                'message': _('%s module(s) du catalogue ajoutés au contrat.') % len(to_add),
                'type': 'success',
                'sticky': False,
            },
        }

    def _migration_dir(self):
        self.ensure_one()
        database = self.client_id.database_name or 'client'
        safe = ''.join(ch if ch.isalnum() or ch in '._-' else '_' for ch in database)
        root = '/opt/odoo/backups/migrations/%s' % safe
        os.makedirs(root, exist_ok=True)
        return root

    def _target_filestore(self):
        self.ensure_one()
        data_dir = (self.client_id.data_directory_path or '').strip()
        if not data_dir or not os.path.isabs(data_dir):
            raise UserError(_('Chemin data-dir du client cible invalide.'))
        data_dir = os.path.realpath(data_dir)
        expected_root = os.path.realpath('/opt/odoo/Odoo-SAAS-Data')
        if os.path.commonpath([expected_root, data_dir]) != expected_root:
            raise UserError(_('Le data-dir du client est hors du répertoire SaaS autorisé.'))
        return os.path.join(data_dir, 'filestore', self.client_id.database_name)

    def _snapshot_target(self, db_server):
        self.ensure_one()
        target_db = self.client_id.database_name
        root = self._migration_dir()
        stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        dump_path = os.path.join(root, '%s-pre-migration-%s.dump' % (target_db, stamp))
        pg_dump = find_pg_tool('pg_dump')
        result = subprocess.run(
            [pg_dump, '--format=custom', '--no-owner', '--file=%s' % dump_path, target_db],
            env=self._pg_env(db_server),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if result.returncode:
            raise UserError(_('Snapshot PostgreSQL impossible : %s') % (result.stderr or result.stdout or b'').decode(errors='ignore'))

        filestore = self._target_filestore()
        files_path = False
        if os.path.isdir(filestore):
            files_path = os.path.join(root, '%s-pre-migration-files-%s.tar.gz' % (target_db, stamp))
            with tarfile.open(files_path, 'w:gz') as archive:
                archive.add(filestore, arcname=os.path.basename(filestore))

        self.write({
            'snapshot_db_path': dump_path,
            'snapshot_filestore_path': files_path,
        })
        self._append_log(_('Snapshot avant migration créé.'))
        self.env.cr.commit()

    def _read_db_properties(self, db_server):
        with closing(self._pg_connect('postgres', db_server)) as connection:
            with closing(connection.cursor()) as cursor:
                cursor.execute(
                    "SELECT pg_encoding_to_char(encoding), datcollate, datctype, pg_get_userbyid(datdba) "
                    "FROM pg_database WHERE datname=%s",
                    (self.client_id.database_name,),
                )
                row = cursor.fetchone()
        if not row:
            raise UserError(_('La base cible n’existe plus.'))
        return {'encoding': row[0], 'collate': row[1], 'ctype': row[2], 'owner': row[3]}

    def _recreate_target_database(self, db_server, properties):
        database = self.client_id.database_name
        with closing(self._pg_connect('postgres', db_server)) as connection:
            connection.autocommit = True
            with closing(connection.cursor()) as cursor:
                cursor.execute(
                    'SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s AND pid<>pg_backend_pid()',
                    (database,),
                )
                cursor.execute(sql.SQL('DROP DATABASE IF EXISTS {}').format(sql.Identifier(database)))
                statement = sql.SQL('CREATE DATABASE {} WITH ENCODING {} LC_COLLATE {} LC_CTYPE {} TEMPLATE template0').format(
                    sql.Identifier(database),
                    sql.Literal(properties['encoding']),
                    sql.Literal(properties['collate']),
                    sql.Literal(properties['ctype']),
                )
                cursor.execute(statement)
        self._append_log(_('Base cible recréée.'))

    def _extract_restore_payload(self, temp_dir):
        backup_path = self.backup_file_id.file_path
        if not zipfile.is_zipfile(backup_path):
            raise UserError(_('Le backup n’est pas un ZIP Odoo valide.'))
        with zipfile.ZipFile(backup_path, 'r') as archive:
            for member in archive.infolist():
                name = (member.filename or '').replace('\\', '/')
                normalized = os.path.normpath(name).replace('\\', '/')
                if name.startswith('/') or normalized == '..' or normalized.startswith('../'):
                    raise UserError(_('Archive ZIP dangereuse : %s') % name)
                if normalized == 'dump.sql' or normalized.startswith('filestore/'):
                    archive.extract(member, temp_dir)
        dump_path = os.path.join(temp_dir, 'dump.sql')
        if not os.path.isfile(dump_path):
            raise UserError(_('dump.sql est absent du ZIP.'))
        filestore = os.path.join(temp_dir, 'filestore')
        return dump_path, filestore if os.path.isdir(filestore) else False

    def _restore_target_database(self, db_server):
        database = self.client_id.database_name
        with tempfile.TemporaryDirectory(prefix='sunapp_saas_migration_') as temp_dir:
            dump_path, source_filestore = self._extract_restore_payload(temp_dir)
            psql = find_pg_tool('psql')
            result = subprocess.run(
                [psql, '--dbname=%s' % database, '-v', 'ON_ERROR_STOP=1', '-q', '-f', dump_path],
                env=self._pg_env(db_server),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            if result.returncode:
                raise UserError(_('Restauration PostgreSQL impossible : %s') % (result.stderr or result.stdout or b'').decode(errors='ignore')[-4000:])

            destination = self._target_filestore()
            os.makedirs(os.path.dirname(destination), exist_ok=True)
            if os.path.isdir(destination):
                shutil.rmtree(destination)
            if source_filestore:
                shutil.copytree(source_filestore, destination)
            else:
                os.makedirs(destination, exist_ok=True)
        self._append_log(_('Base et filestore restaurés.'))

    def _neutralize_restored_database(self, db_server):
        database = self.client_id.database_name
        with closing(self._pg_connect(database, db_server)) as connection:
            with closing(connection.cursor()) as cursor:
                cursor.execute("SELECT id FROM ir_cron WHERE active IS TRUE ORDER BY id")
                cron_ids = [row[0] for row in cursor.fetchall()]
                cursor.execute("SELECT id FROM ir_mail_server WHERE active IS TRUE ORDER BY id")
                smtp_ids = [row[0] for row in cursor.fetchall()]
                cursor.execute("UPDATE ir_config_parameter SET value=%s WHERE key='web.base.url'", (self.client_id.client_url,))
                cursor.execute("UPDATE ir_cron SET active=FALSE WHERE active IS TRUE")
                cursor.execute("UPDATE ir_mail_server SET active=FALSE WHERE active IS TRUE")
            connection.commit()
        self.write({
            'cron_ids_json': json.dumps(cron_ids),
            'smtp_ids_json': json.dumps(smtp_ids),
        })
        self._append_log(_('URL cible appliquée ; crons et SMTP temporairement désactivés.'))

    def _reconcile_module_status(self, db_server):
        database = self.client_id.database_name
        with closing(self._pg_connect(database, db_server)) as connection:
            with closing(connection.cursor()) as cursor:
                cursor.execute("SELECT name FROM ir_module_module WHERE state='installed'")
                installed = {row[0] for row in cursor.fetchall()}
        for status in self.client_id.saas_module_ids:
            technical = status.module_id.technical_name
            status.sudo().write({'status': 'installed' if technical in installed else 'uninstalled'})
        if 'missed_modules' in self.client_id._fields:
            self.client_id.sudo().write({'missed_modules': False})
        self._append_log(_('Statuts modules SaaS réconciliés avec la base restaurée.'))

    def _disable_auto_restart_and_stop(self, host_server, db_server):
        client = self.client_id
        vals = {}
        if 'auto_restart_enabled' in client._fields:
            vals['auto_restart_enabled'] = False
        if 'auto_restart_intentional_stop' in client._fields:
            vals['auto_restart_intentional_stop'] = True
        if vals:
            client.sudo().write(vals)
            # Le moniteur SaaS doit voir la neutralisation avant l'arrêt Docker.
            self.env.cr.commit()
        if client.container_id and client.state == 'started':
            if not containers.action(operation='stop', container_id=client.container_id, host_server=host_server, db_server=db_server):
                raise UserError(_('Impossible d’arrêter le conteneur du client.'))
            client.sudo().write({'state': 'stopped'})
        self._append_log(_('Auto-restart neutralisé et conteneur arrêté.'))
        self.env.cr.commit()

    def _post_restore_upgrade_modules(self, db_server):
        """Aligne le schéma des modules sensibles après restauration."""
        self.ensure_one()

        database = self.client_id.database_name
        container_id = self.client_id.container_id

        if not container_id:
            raise UserError(
                _('Le client cible ne possède pas de conteneur Docker.')
            )

        with closing(self._pg_connect(database, db_server)) as connection:
            with closing(connection.cursor()) as cursor:
                cursor.execute(
                    """
                    SELECT name
                    FROM ir_module_module
                    WHERE state = 'installed'
                      AND name = ANY(%s)
                    """,
                    (list(self._POST_RESTORE_UPGRADE_MODULES),),
                )
                installed = {row[0] for row in cursor.fetchall()}

        modules = [
            module
            for module in self._POST_RESTORE_UPGRADE_MODULES
            if module in installed
        ]

        if not modules:
            self._append_log(
                _('Aucun module de réconciliation post-restauration détecté.')
            )
            return False

        module_arg = ','.join(modules)

        docker = shutil.which('docker')
        if not docker:
            raise UserError(
                _('Commande Docker introuvable sur le serveur SaaS.')
            )

        self._append_log(
            _('Mise à niveau post-restauration : %s') % module_arg
        )
        self.env.cr.commit()

        result = subprocess.run(
            [
                docker,
                'exec',
                str(container_id),
                'python3',
                '/opt/odoo/odoo-bin',
                '-c',
                '/etc/odoo/odoo-server.conf',
                '-d',
                database,
                '-u',
                module_arg,
                '--stop-after-init',
                '--no-http',
                '--logfile=/opt/data-dir/post-restore-upgrade.log',
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=900,
        )

        if result.returncode:
            output = (
                result.stderr
                or result.stdout
                or b''
            ).decode(errors='ignore')[-4000:]

            raise UserError(
                _(
                    'Mise à niveau post-restauration impossible '
                    'pour %(modules)s : %(error)s',
                    modules=module_arg,
                    error=output,
                )
            )

        self._append_log(
            _('Mise à niveau post-restauration terminée : %s') % module_arg
        )
        self.env.cr.commit()

        restart = subprocess.run(
            [
                docker,
                'restart',
                str(container_id),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=120,
        )

        if restart.returncode:
            output = (
                restart.stderr
                or restart.stdout
                or b''
            ).decode(errors='ignore')[-2000:]

            raise UserError(
                _('Redémarrage du client après upgrade impossible : %s')
                % output
            )

        self._append_log(
            _('Conteneur redémarré après réconciliation des modules.')
        )

        # Laisser quelques secondes à Odoo pour reconstruire son registry.
        time.sleep(8)

        return True

    def _start_client(self, host_server, db_server):
        client = self.client_id
        if client.container_id:
            if not containers.action(operation='start', container_id=client.container_id, host_server=host_server, db_server=db_server):
                raise UserError(_('La restauration est terminée mais le conteneur n’a pas pu démarrer.'))
            client.sudo().write({'state': 'started'})
        self._append_log(_('Conteneur client démarré.'))

    def _check_http(self):
        status = 0
        try:
            response = requests.get(self.client_id.client_url, timeout=20, allow_redirects=True)
            status = int(response.status_code)
        except Exception as error:
            self._append_log(_('Contrôle HTTP non concluant : %s') % error)
        self.http_status = status
        return status

    def action_launch_migration(self):
        self.ensure_one()
        self._require_admin()
        if self.state != 'analyzed' or self.runtime_missing_count:
            raise UserError(_('Analysez d’abord la cible et corrigez tous les modules runtime manquants.'))
        if not self.confirm_migration:
            raise UserError(_('Vous devez confirmer la restauration destructive de la base cible.'))
        if not self.client_id or not self.client_id.database_name:
            raise UserError(_('Client cible invalide.'))

        host_server, db_server = self._server_context()

        self.write({'state': 'running', 'error_message': False})
        self._append_log(_('Début de la migration.'))
        self.env.cr.commit()

        try:
            properties = self._read_db_properties(db_server)
            self._disable_auto_restart_and_stop(host_server, db_server)
            self._snapshot_target(db_server)
            if self.sync_contract_modules:
                self.action_sync_contract_modules()
            self._recreate_target_database(db_server, properties)
            self._restore_target_database(db_server)
            self._neutralize_restored_database(db_server)
            self._reconcile_module_status(db_server)
            self._start_client(host_server, db_server)
            self._post_restore_upgrade_modules(db_server)
            self._check_http()
            self.write({'state': 'validation'})
            self._append_log(_('Migration restaurée. Validation utilisateur requise avant finalisation.'))
            self.env.cr.commit()
        except Exception as error:
            _logger.exception('Migration SaaS échouée pour %s', self.name)
            self.write({'state': 'failed', 'error_message': str(error)})
            self._append_log(_('ÉCHEC : %s') % error)
            self.env.cr.commit()
            raise UserError(_('Migration échouée : %s') % error)

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'saas.backup.migration',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_finalize(self):
        self.ensure_one()
        self._require_admin()
        if self.state != 'validation':
            raise UserError(_('La migration doit être en attente de validation.'))
        host_server, db_server = self._server_context()
        cron_ids = json.loads(self.cron_ids_json or '[]')
        smtp_ids = json.loads(self.smtp_ids_json or '[]')
        with closing(self._pg_connect(self.client_id.database_name, db_server)) as connection:
            with closing(connection.cursor()) as cursor:
                if cron_ids:
                    cursor.execute('UPDATE ir_cron SET active=TRUE WHERE id = ANY(%s)', (cron_ids,))
                if smtp_ids:
                    cursor.execute('UPDATE ir_mail_server SET active=TRUE WHERE id = ANY(%s)', (smtp_ids,))
            connection.commit()
        vals = {}
        if 'auto_restart_enabled' in self.client_id._fields:
            vals['auto_restart_enabled'] = True
        if 'auto_restart_intentional_stop' in self.client_id._fields:
            vals['auto_restart_intentional_stop'] = False
        if vals:
            self.client_id.sudo().write(vals)
        if self.client_id.state != 'started' and self.client_id.container_id:
            if not containers.action(operation='start', container_id=self.client_id.container_id, host_server=host_server, db_server=db_server):
                raise UserError(_('Impossible de démarrer le client pendant la finalisation.'))
            self.client_id.sudo().write({'state': 'started'})
        self.write({'state': 'done'})
        self._append_log(_('Migration finalisée : crons/SMTP historiques restaurés et auto-restart activé.'))
        return True
