# -*- coding: utf-8 -*-
import logging
import os
import shutil
import subprocess
import tempfile
import uuid
import zipfile
from contextlib import closing
from configparser import RawConfigParser

import odoo.service.db as db_service
import psycopg2
from psycopg2.extensions import quote_ident
from odoo import _, api, fields, models
from odoo.exceptions import AccessDenied, UserError
from odoo.tools.config import crypt_context
from odoo.tools.misc import find_pg_tool

_logger = logging.getLogger(__name__)


class SaasBackupRestoreWizard(models.TransientModel):
    """Assistant de restauration d'une sauvegarde SaaS.

    Deux modes :
    - 'new'       → Restaure le backup dans une nouvelle base de données
                    (la base ne doit pas encore exister)
    - 'overwrite' → Supprime la base existante et la recrée depuis le backup
                    (⚠️ toutes les données actuelles sont perdues)
    """
    _name = 'saas.backup.restore.wizard'
    _description = 'Assistant de restauration Backup SaaS'

    backup_file_id = fields.Many2one(
        'saas.backup.file',
        string='Fichier de sauvegarde',
        readonly=True,
        required=True,
    )
    backup_name = fields.Char(
        related='backup_file_id.name',
        string='Fichier',
        readonly=True,
    )
    backup_client = fields.Char(
        related='backup_file_id.client_name',
        string='Client',
        readonly=True,
    )
    backup_date = fields.Datetime(
        related='backup_file_id.backup_date',
        string='Date du backup',
        readonly=True,
    )

    mode = fields.Selection([
        ('new', 'Nouvelle base de données'),
        ('overwrite', '⚠️ Écraser une base existante'),
    ], string='Mode de restauration', required=True, default='new')

    db_name = fields.Char(
        string='Nom de la base cible',
        required=True,
        help="Nom de la base PostgreSQL. Pour 'Nouvelle base', elle ne doit pas encore exister. "
             "Pour 'Écraser', elle sera supprimée puis recréée.",
    )
    master_password = fields.Char(
        string='Mot de passe maître Odoo',
        password=True,
        help="Le mot de passe maître du serveur Odoo (admin_passwd dans odoo.conf).",
    )
    neutralize = fields.Boolean(
        string='Neutraliser la base',
        default=True,
        help="Génère un nouvel identifiant unique (UUID) pour la base restaurée. "
             "Recommandé pour éviter les conflits avec la base d'origine.",
    )
    confirm_overwrite = fields.Boolean(
        string="Je confirme vouloir supprimer la base existante",
        default=False,
    )

    # -------------------------------------------------------------------------
    # Onchange
    # -------------------------------------------------------------------------

    @api.onchange('backup_file_id')
    def _onchange_backup_file_id(self):
        self._set_default_target_database_name()

    @api.onchange('mode')
    def _onchange_mode(self):
        self._set_default_target_database_name()

    # -------------------------------------------------------------------------
    # Action principale
    # -------------------------------------------------------------------------

    def action_restore(self):
        """Lance la restauration après vérification des paramètres."""
        self.ensure_one()

        # 1. Vérifier le mot de passe maître
        if not self.master_password:
            raise UserError(_("Le mot de passe maître Odoo est obligatoire."))
        if not self._check_restore_master_password(self.master_password):
            raise UserError(_(
                "Mot de passe maître incorrect. Vérifiez la valeur de 'admin_passwd' "
                "dans la configuration Odoo principale ou dans le fichier "
                "odoo-server.conf de l'instance sauvegardée."
            ))

        # 2. Vérifier le fichier backup
        file_path = self.backup_file_id.file_path
        if not file_path or not os.path.isfile(file_path):
            self.backup_file_id.write({'state': 'missing'})
            raise UserError(_(
                "Le fichier de sauvegarde '%(name)s' n'existe plus sur le serveur.",
                name=self.backup_file_id.name,
            ))

        db_name = (self.db_name or '').strip()
        if not db_name:
            raise UserError(_("Le nom de la base cible est obligatoire."))

        instance_db_config = self._get_instance_db_config()
        existing_dbs = self._list_existing_databases(instance_db_config)

        if self.mode == 'new' and db_name in existing_dbs:
            raise UserError(_(
                "La base cible '%(db)s' existe déjà. Choisissez un autre nom pour "
                "créer une nouvelle base, ou utilisez le mode 'Écraser une base existante'.",
                db=db_name,
            ))

        # 3. Mode 'overwrite' : demander confirmation et supprimer l'existante
        if self.mode == 'overwrite':
            if not self.confirm_overwrite:
                raise UserError(_(
                    "Vous devez cocher la case de confirmation pour écraser une base existante."
                ))
            if db_name not in existing_dbs:
                suggested_db = self._get_backup_database_name()
                message = _(
                    "La base cible '%(db)s' n'existe pas, donc elle ne peut pas être écrasée.",
                    db=db_name,
                )
                if suggested_db:
                    message += _(
                        "\n\nPour remplacer la base sauvegardée, utilisez exactement : %(db)s",
                        db=suggested_db,
                    )
                raise UserError(message)
            if db_name in existing_dbs:
                _logger.warning(
                    "Restauration SaaS : suppression de la base '%s' demandée par '%s'",
                    db_name, self.env.user.name,
                )
                try:
                    if instance_db_config:
                        self._drop_database_with_config(db_name, instance_db_config)
                    else:
                        db_service.exp_drop(db_name)
                except Exception as e:
                    raise UserError(_(
                        "Impossible de supprimer la base '%(db)s' : %(error)s",
                        db=db_name, error=str(e),
                    ))

        # 4. Lancer la restauration
        _logger.info(
            "Restauration SaaS : '%s' → base '%s' par '%s'",
            self.backup_file_id.name, db_name, self.env.user.name,
        )
        try:
            if instance_db_config:
                self._restore_database_with_config(db_name, file_path, instance_db_config)
            else:
                db_service.restore_db(
                    db_name,
                    file_path,
                    copy=self.neutralize,
                    neutralize_database=self.neutralize,
                )
        except Exception as e:
            raise UserError(_(
                "Erreur lors de la restauration : %(error)s",
                error=str(e),
            ))

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Restauration réussie"),
                'message': _(
                    "La base '%(db)s' a été restaurée depuis '%(file)s'.",
                    db=db_name,
                    file=self.backup_file_id.name,
                ),
                'type': 'success',
                'sticky': True,
            },
        }

    def _set_default_target_database_name(self):
        for wizard in self:
            if not wizard.backup_file_id:
                continue
            if wizard.mode == 'overwrite':
                wizard.db_name = wizard._get_backup_database_name()
            else:
                wizard.db_name = wizard._get_suggested_new_database_name()

    def _get_backup_database_name(self):
        self.ensure_one()
        return self.backup_file_id.database_name or self.backup_file_id.client_name or ''

    def _get_suggested_new_database_name(self):
        self.ensure_one()
        source_name = self._get_backup_database_name()
        if not source_name:
            return ''
        return source_name.replace(
            '.odoo.sunsoftbf.com', ''
        ).replace('.', '_').replace('-', '_').lower()

    def _check_restore_master_password(self, password):
        self.ensure_one()
        try:
            db_service.check_super(password)
            return True
        except AccessDenied:
            pass

        instance_admin_password = self._get_instance_admin_password()
        if not instance_admin_password:
            return False
        if instance_admin_password == password:
            return True
        try:
            return bool(crypt_context.verify(password, instance_admin_password))
        except Exception:
            _logger.exception("Impossible de vérifier le mot de passe maître de l'instance SaaS.")
            return False

    def _get_instance_admin_password(self):
        self.ensure_one()
        for config_path in self._get_instance_config_paths():
            admin_password = self._read_admin_password_from_config(config_path)
            if admin_password:
                return admin_password
        return False

    def _get_instance_db_config(self):
        self.ensure_one()
        for config_path in self._get_instance_config_paths():
            parser = self._read_instance_config(config_path)
            if not parser:
                continue
            options = parser['options']
            db_user = (options.get('db_user') or '').strip()
            if not db_user:
                continue
            return {
                'host': (options.get('db_host') or 'localhost').strip(),
                'port': (options.get('db_port') or '5432').strip(),
                'user': db_user,
                'password': (options.get('db_password') or '').strip(),
                'data_dir': (options.get('data_dir') or '').strip(),
                'config_path': config_path,
            }
        return False

    def _list_existing_databases(self, db_config=False):
        if not db_config:
            return db_service.list_dbs(True)
        with closing(self._pg_connect('postgres', db_config)) as connection:
            with closing(connection.cursor()) as cursor:
                cursor.execute("""
                    SELECT datname
                      FROM pg_database
                     WHERE NOT datistemplate
                       AND datallowconn
                     ORDER BY datname
                """)
                return [row[0] for row in cursor.fetchall()]

    def _pg_connect(self, database_name, db_config):
        return psycopg2.connect(
            dbname=database_name,
            host=db_config.get('host') or None,
            port=db_config.get('port') or None,
            user=db_config.get('user') or None,
            password=db_config.get('password') or None,
        )

    def _drop_database_with_config(self, db_name, db_config):
        with closing(self._pg_connect('postgres', db_config)) as connection:
            connection.autocommit = True
            with closing(connection.cursor()) as cursor:
                cursor.execute("""
                    SELECT pg_terminate_backend(pid)
                      FROM pg_stat_activity
                     WHERE datname = %s
                       AND pid <> pg_backend_pid()
                """, (db_name,))
                cursor.execute("DROP DATABASE %s" % quote_ident(db_name, cursor))
        self._remove_instance_filestore(db_name)

    def _restore_database_with_config(self, db_name, file_path, db_config):
        self._create_database_with_config(db_name, db_config)
        try:
            self._load_dump_into_database(db_name, file_path, db_config)
            if self.neutralize:
                self._neutralize_database_uuid(db_name, db_config)
        except Exception:
            _logger.exception("Restauration SaaS : échec, suppression de la base incomplète %s", db_name)
            try:
                self._drop_database_with_config(db_name, db_config)
            except Exception:
                _logger.exception("Impossible de nettoyer la base restaurée partiellement %s", db_name)
            raise

    def _create_database_with_config(self, db_name, db_config):
        with closing(self._pg_connect('postgres', db_config)) as connection:
            connection.autocommit = True
            with closing(connection.cursor()) as cursor:
                cursor.execute(
                    "CREATE DATABASE %s ENCODING 'unicode'"
                    % quote_ident(db_name, cursor)
                )

    def _load_dump_into_database(self, db_name, file_path, db_config):
        with tempfile.TemporaryDirectory(prefix='saas_restore_') as dump_dir:
            dump_path = file_path
            filestore_path = False
            if zipfile.is_zipfile(file_path):
                dump_path, filestore_path = self._extract_backup_zip(file_path, dump_dir)
                command = [find_pg_tool('psql'), '--dbname=%s' % db_name, '-q', '-f', dump_path]
            else:
                command = [find_pg_tool('pg_restore'), '--no-owner', '--dbname=%s' % db_name, dump_path]

            result = subprocess.run(
                command,
                env=self._pg_subprocess_env(db_config),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            if result.returncode:
                raise UserError(_(
                    "La commande de restauration PostgreSQL a échoué : %(error)s",
                    error=(result.stderr or result.stdout or b'').decode(errors='ignore').strip(),
                ))

            if filestore_path:
                self._replace_instance_filestore(db_name, filestore_path)

    def _extract_backup_zip(self, file_path, dump_dir):
        with zipfile.ZipFile(file_path, 'r') as archive:
            for member in archive.infolist():
                normalized_name = os.path.normpath(member.filename)
                if normalized_name.startswith('..') or os.path.isabs(normalized_name):
                    continue
                if normalized_name == 'dump.sql' or normalized_name.startswith('filestore/'):
                    archive.extract(member, dump_dir)

        dump_path = os.path.join(dump_dir, 'dump.sql')
        if not os.path.isfile(dump_path):
            raise UserError(_("Le fichier ZIP ne contient pas de dump.sql."))
        filestore_path = os.path.join(dump_dir, 'filestore')
        return dump_path, filestore_path if os.path.isdir(filestore_path) else False

    def _pg_subprocess_env(self, db_config):
        env = os.environ.copy()
        if db_config.get('host'):
            env['PGHOST'] = db_config['host']
        if db_config.get('port'):
            env['PGPORT'] = db_config['port']
        if db_config.get('user'):
            env['PGUSER'] = db_config['user']
        if db_config.get('password'):
            env['PGPASSWORD'] = db_config['password']
        return env

    def _neutralize_database_uuid(self, db_name, db_config):
        with closing(self._pg_connect(db_name, db_config)) as connection:
            with closing(connection.cursor()) as cursor:
                cursor.execute("""
                    UPDATE ir_config_parameter
                       SET value = %s
                     WHERE key = 'database.uuid'
                """, (str(uuid.uuid4()),))
            connection.commit()

    def _replace_instance_filestore(self, db_name, source_filestore_path):
        destination = self._get_instance_filestore_path(db_name)
        if not destination:
            _logger.warning("Restauration SaaS : chemin filestore introuvable pour %s", db_name)
            return
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        if os.path.isdir(destination):
            shutil.rmtree(destination)
        shutil.move(source_filestore_path, destination)

    def _remove_instance_filestore(self, db_name):
        destination = self._get_instance_filestore_path(db_name)
        if destination and os.path.isdir(destination):
            shutil.rmtree(destination)

    def _get_instance_filestore_path(self, db_name):
        storage_path = self._get_backup_process_storage_path()
        if storage_path:
            storage_path = os.path.abspath(os.path.expanduser(storage_path))
            if os.path.basename(storage_path.rstrip(os.sep)) == 'data-dir':
                return os.path.join(storage_path, 'filestore', db_name)
            return os.path.join(storage_path, 'data-dir', 'filestore', db_name)

        instance_config = self._get_instance_db_config()
        data_dir = instance_config and instance_config.get('data_dir')
        if data_dir and os.path.isabs(data_dir):
            return os.path.join(data_dir, 'filestore', db_name)
        return False

    def _get_instance_config_paths(self):
        self.ensure_one()
        candidates = []

        storage_path = self._get_backup_process_storage_path()
        if storage_path:
            instance_path = self._get_instance_path_from_storage(storage_path)
            if instance_path:
                candidates.append(os.path.join(instance_path, 'odoo-server.conf'))

        file_path = self.backup_file_id.file_path
        if file_path:
            backup_dir = os.path.dirname(os.path.abspath(os.path.expanduser(file_path)))
            if os.path.basename(backup_dir) == 'backups':
                candidates.append(os.path.join(os.path.dirname(backup_dir), 'odoo-server.conf'))

        seen = set()
        paths = []
        for path in candidates:
            path = os.path.abspath(os.path.expanduser(path))
            if path in seen:
                continue
            seen.add(path)
            if os.path.isfile(path):
                paths.append(path)
        return paths

    def _get_backup_process_storage_path(self):
        self.ensure_one()
        process = self.backup_file_id.backup_process_id
        if not process:
            return False
        for field_name in ('storage_path', 'backup_path', 'path', 'local_path'):
            if field_name in process._fields and process[field_name]:
                return process[field_name]
        return False

    def _get_instance_path_from_storage(self, storage_path):
        storage_path = os.path.abspath(os.path.expanduser(storage_path or ''))
        if os.path.basename(storage_path.rstrip(os.sep)) == 'data-dir':
            return os.path.dirname(storage_path)
        return storage_path

    def _read_admin_password_from_config(self, config_path):
        parser = self._read_instance_config(config_path)
        if not parser or not parser.has_option('options', 'admin_passwd'):
            return False
        return (parser.get('options', 'admin_passwd') or '').strip()

    def _read_instance_config(self, config_path):
        parser = RawConfigParser()
        try:
            parser.read(config_path)
        except Exception:
            _logger.exception("Impossible de lire le fichier de configuration %s", config_path)
            return False
        if not parser.has_section('options'):
            return False
        return parser
