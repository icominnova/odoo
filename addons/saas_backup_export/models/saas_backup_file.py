# -*- coding: utf-8 -*-
import hashlib
import hmac
import logging
import os
from datetime import datetime

import odoo.service.db as db_service
from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class SaasBackupFile(models.Model):
    """Représente un fichier de sauvegarde ZIP trouvé sur le système de fichiers.

    L'action 'Scanner les backups' parcourt le dossier racine configuré
    et crée/met à jour un enregistrement par fichier ZIP trouvé.
    """
    _name = 'saas.backup.file'
    _description = 'Fichier de sauvegarde SaaS'
    _order = 'backup_date desc, client_name'

    name = fields.Char(string='Nom du fichier', readonly=True)
    backup_process_id = fields.Many2one(
        'backup.process',
        string='Backup Process',
        readonly=True,
        index=True,
        ondelete='set null',
    )
    database_name = fields.Char(string='Base de données', readonly=True, index=True)
    client_name = fields.Char(string='Client', readonly=True, index=True)
    file_path = fields.Char(string='Chemin complet', readonly=True)
    file_size_mb = fields.Float(string='Taille (Mo)', readonly=True, digits=(16, 2))
    backup_date = fields.Datetime(string='Date de sauvegarde', readonly=True)
    state = fields.Selection([
        ('available', 'Disponible'),
        ('missing', 'Fichier manquant'),
    ], string='État', default='available', readonly=True)
    download_token = fields.Char(
        string='Token de téléchargement',
        readonly=True,
        copy=False,
        help="Token sécurisé utilisé pour l'URL de téléchargement.",
    )
    download_url = fields.Char(
        string="Lien de téléchargement",
        compute='_compute_download_url',
    )
    relative_path = fields.Char(string='Chemin relatif', readonly=True)

    # -------------------------------------------------------------------------
    # Compute
    # -------------------------------------------------------------------------

    def _compute_download_url(self):
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        for record in self:
            if record.download_token and record.state == 'available':
                record.download_url = (
                    f"{base_url}/saas/backup/download"
                    f"?id={record.id}&token={record.download_token}"
                )
            else:
                record.download_url = False

    # -------------------------------------------------------------------------
    # Actions
    # -------------------------------------------------------------------------

    def action_scan_backups(self):
        """Scanne le dossier racine configuré et crée/met à jour les enregistrements
        pour chaque fichier ZIP trouvé dans les sous-dossiers clients.
        """
        base_path = self._get_base_path()
        found_paths = set()
        created = updated = 0

        for vals in self._iter_backup_files(base_path, recursive=True):
            found_paths.add(vals['file_path'])
            record, was_created = self._upsert_backup_file(vals)
            if was_created:
                created += 1
            else:
                updated += 1

        # Chercher également les ZIP stockés dans le filestore via ir.attachment
        created, updated, found_paths = self._scan_filestore_zip_attachments(
            found_paths, created, updated
        )

        # Marquer comme manquants les fichiers qui n'existent plus
        missing = self.search([
            ('file_path', 'not in', list(found_paths)),
            ('state', '=', 'available'),
        ])
        missing.write({'state': 'missing'})

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Scan terminé"),
                'message': _(
                    "%(created)s fichier(s) ajouté(s), %(updated)s mis à jour, "
                    "%(missing)s marqué(s) comme manquant(s).",
                    created=created,
                    updated=updated,
                    missing=len(missing),
                ),
                'type': 'success',
                'sticky': False,
            },
        }

    @api.model
    def action_create_backup_for_process(self, process):
        process = process.sudo()
        database_name = self._get_backup_process_value(
            process,
            ('database_name', 'db_name', 'database', 'client_db_name'),
        )
        storage_path = self._get_backup_process_value(
            process,
            ('storage_path', 'backup_path', 'path', 'local_path'),
        )
        if not database_name:
            raise UserError(_("Impossible de trouver le nom de base sur le Backup Process."))
        if not storage_path:
            raise UserError(_("Impossible de trouver le Storage Path sur le Backup Process."))

        backup_dir = self._get_process_backup_dir(storage_path)
        os.makedirs(backup_dir, exist_ok=True)

        timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        filename = '%s_%s.zip' % (database_name, timestamp)
        full_path = os.path.join(backup_dir, filename)

        try:
            with open(full_path, 'wb') as stream:
                db_service.dump_db(database_name, stream, backup_format='zip', with_filestore=True)
        except Exception as error:
            if os.path.exists(full_path):
                try:
                    os.unlink(full_path)
                except OSError:
                    pass
            raise UserError(_("Erreur lors de la sauvegarde de %(db)s : %(error)s", db=database_name, error=error))

        vals = self._backup_file_values(
            full_path,
            database_name=database_name,
            client_name=database_name,
            backup_process_id=process.id,
            relative_root=backup_dir,
        )
        record, _created = self._upsert_backup_file(vals)
        return record

    @api.model
    def action_scan_process_backups(self, process):
        process = process.sudo()
        database_name = self._get_backup_process_value(
            process,
            ('database_name', 'db_name', 'database', 'client_db_name'),
        )
        storage_path = self._get_backup_process_value(
            process,
            ('storage_path', 'backup_path', 'path', 'local_path'),
        )
        if not database_name:
            raise UserError(_("Impossible de trouver le nom de base sur le Backup Process."))
        if not storage_path:
            raise UserError(_("Impossible de trouver le Storage Path sur le Backup Process."))

        backup_dir = self._get_process_backup_dir(storage_path)
        if not os.path.isdir(backup_dir):
            return self

        records = self
        for filename in sorted(os.listdir(backup_dir), key=str.lower):
            full_path = os.path.join(backup_dir, filename)
            if not os.path.isfile(full_path) or not filename.lower().endswith('.zip'):
                continue
            vals = self._backup_file_values(
                full_path,
                database_name=database_name,
                client_name=database_name,
                backup_process_id=process.id,
                relative_root=backup_dir,
            )
            record, _created = self._upsert_backup_file(vals)
            records |= record
        return records

    @api.model
    def cron_create_backups_for_all_processes(self):
        processes = self.env['backup.process'].sudo().search([])
        for process in processes:
            try:
                self.action_create_backup_for_process(process)
            except Exception:
                _logger.exception(
                    "Erreur lors de la sauvegarde automatique du process %s",
                    process.display_name,
                )
        return True

    def action_download(self):
        """Retourne l'URL de téléchargement sécurisée pour le fichier backup."""
        self.ensure_one()
        if self.state == 'missing':
            raise UserError(_("Le fichier de sauvegarde n'existe plus sur le serveur."))
        if not self.download_url:
            raise UserError(_("Impossible de générer le lien de téléchargement."))
        return {
            'type': 'ir.actions.act_url',
            'url': self.download_url,
            'target': 'self',
        }

    def action_download_archive(self):
        records = self.filtered(lambda record: record.state == 'available')
        if not records:
            raise UserError(_("Aucun fichier disponible à exporter."))
        if len(records) == 1:
            return records.action_download()

        ids = ','.join(str(record.id) for record in records.sorted('id'))
        token = self._generate_archive_token(records)
        return {
            'type': 'ir.actions.act_url',
            'url': f'/saas/backup/download_archive?ids={ids}&token={token}',
            'target': 'self',
        }

    def action_open_restore_wizard(self):
        """Ouvre le wizard de restauration pré-rempli avec ce fichier backup."""
        self.ensure_one()
        if self.state == 'missing':
            raise UserError(_(
                "Le fichier de sauvegarde n'existe plus sur le serveur."
            ))
        # Proposer un nom de base à partir du dossier client
        suggested_name = (
            self.client_name
            .replace('.odoo.sunsoftbf.com', '')
            .replace('.', '_')
            .replace('-', '_')
            .lower()
        ) if self.client_name else ''

        wizard = self.env['saas.backup.restore.wizard'].create({
            'backup_file_id': self.id,
            'db_name': suggested_name,
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'saas.backup.restore.wizard',
            'view_mode': 'form',
            'res_id': wizard.id,
            'target': 'new',
            'name': _('Restauration — %s') % self.name,
        }

    def action_mark_missing(self):
        """Vérifie si le fichier existe encore et met à jour l'état."""
        for record in self:
            if os.path.isfile(record.file_path):
                record.state = 'available'
            else:
                record.state = 'missing'

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _scan_filestore_zip_attachments(self, found_paths, created, updated):
        attachments = self.env['ir.attachment'].sudo().search([
            '&', ('store_fname', '!=', False),
            '|',
            ('mimetype', '=', 'application/zip'),
            ('name', 'ilike', '%.zip'),
        ])
        for attach in attachments:
            store_fname = attach.store_fname
            if not store_fname:
                continue
            try:
                full_path = self.env['ir.attachment']._full_path(store_fname)
            except Exception:
                continue
            if not os.path.isfile(full_path):
                continue

            name = attach.name or os.path.basename(full_path)
            client_name = attach.res_name or attach.res_model or 'Filestore'
            stat = os.stat(full_path)
            size_mb = stat.st_size / (1024 * 1024)
            backup_date = datetime.fromtimestamp(stat.st_mtime)

            found_paths.add(full_path)
            existing = self.search([('file_path', '=', full_path)], limit=1)
            if existing:
                existing.write({
                    'name': name,
                    'database_name': client_name,
                    'client_name': client_name,
                    'file_size_mb': size_mb,
                    'backup_date': backup_date,
                    'relative_path': name,
                    'state': 'available',
                })
                updated += 1
            else:
                token = self._generate_token(full_path)
                self.create({
                    'name': name,
                    'database_name': client_name,
                    'client_name': client_name,
                    'file_path': full_path,
                    'file_size_mb': size_mb,
                    'backup_date': backup_date,
                    'relative_path': name,
                    'state': 'available',
                    'download_token': token,
                })
                created += 1
        return created, updated, found_paths

    @api.model
    def _get_config(self):
        config = self.env['saas.backup.config'].search([('active', '=', True)], limit=1)
        if not config:
            raise UserError(_(
                "Aucune configuration active trouvée. Configurez d'abord "
                "le dossier racine des backups."
            ))
        return config

    @api.model
    def _get_base_path(self):
        base_path = os.path.abspath(os.path.expanduser(self._get_config().base_path or ''))
        if not os.path.isdir(base_path):
            raise UserError(_(
                "Le dossier %(path)s n'existe pas ou n'est pas accessible.",
                path=base_path,
            ))
        return base_path

    @api.model
    def _get_backup_process_value(self, process, field_names):
        if not process:
            return False
        for field_name in field_names:
            if field_name not in process._fields:
                continue
            value = process[field_name]
            if hasattr(value, 'display_name'):
                return value.display_name
            return value
        return False

    @api.model
    def _get_process_backup_dir(self, storage_path):
        storage_path = os.path.abspath(os.path.expanduser(storage_path or ''))
        if os.path.basename(storage_path.rstrip(os.sep)) == 'data-dir':
            instance_path = os.path.dirname(storage_path)
        else:
            instance_path = storage_path
        return os.path.join(instance_path, 'backups')

    @api.model
    def _backup_file_values(self, full_path, database_name=False, client_name=False, backup_process_id=False, relative_root=False):
        stat = os.stat(full_path)
        return {
            'name': os.path.basename(full_path),
            'backup_process_id': backup_process_id,
            'database_name': database_name or client_name,
            'client_name': client_name or database_name,
            'file_path': full_path,
            'file_size_mb': stat.st_size / (1024 * 1024),
            'backup_date': datetime.fromtimestamp(stat.st_mtime),
            'relative_path': os.path.relpath(full_path, relative_root) if relative_root else os.path.basename(full_path),
            'state': 'available',
        }

    @api.model
    def _iter_client_folders(self, base_path=None):
        base_path = base_path or self._get_base_path()
        try:
            entries = sorted(os.listdir(base_path), key=str.lower)
        except OSError as error:
            raise UserError(_("Impossible de lire le dossier %(path)s : %(error)s", path=base_path, error=error))

        folders = []
        for name in entries:
            full_path = os.path.join(base_path, name)
            if os.path.isdir(full_path):
                folders.append((name, name))
        return folders

    @api.model
    def _safe_client_path(self, base_path, client_folder):
        if not client_folder:
            raise UserError(_("Veuillez choisir une base de donnees."))

        base_real = os.path.realpath(base_path)
        folder_real = os.path.realpath(os.path.join(base_real, client_folder))
        if os.path.commonpath([base_real, folder_real]) != base_real:
            raise UserError(_("Le dossier selectionne n'est pas valide."))
        if not os.path.isdir(folder_real):
            raise UserError(_("Le dossier %(path)s n'existe pas sur le serveur.", path=folder_real))
        return folder_real

    @api.model
    def _iter_backup_files(self, base_path, client_folder=None, recursive=True):
        if client_folder:
            folders = [(client_folder, self._safe_client_path(base_path, client_folder))]
        else:
            folders = [
                (name, os.path.join(base_path, name))
                for name, _label in self._iter_client_folders(base_path)
            ]

        for client_name, client_path in folders:
            if recursive:
                walker = os.walk(client_path)
                for root, _dirs, files in walker:
                    for filename in sorted(files, key=str.lower):
                        if filename.lower().endswith('.zip'):
                            yield self._file_values(base_path, client_name, os.path.join(root, filename))
            else:
                for filename in sorted(os.listdir(client_path), key=str.lower):
                    full_path = os.path.join(client_path, filename)
                    if os.path.isfile(full_path) and filename.lower().endswith('.zip'):
                        yield self._file_values(base_path, client_name, full_path)

    @api.model
    def _file_values(self, base_path, client_name, full_path):
        stat = os.stat(full_path)
        return {
            'name': os.path.basename(full_path),
            'database_name': client_name,
            'client_name': client_name,
            'file_path': full_path,
            'file_size_mb': stat.st_size / (1024 * 1024),
            'backup_date': datetime.fromtimestamp(stat.st_mtime),
            'relative_path': os.path.relpath(full_path, base_path),
            'state': 'available',
        }

    @api.model
    def _upsert_backup_file(self, vals):
        existing = self.search([('file_path', '=', vals['file_path'])], limit=1)
        if existing:
            existing.write(vals)
            return existing, False

        vals = dict(vals, download_token=self._generate_token(vals['file_path']))
        return self.create(vals), True

    @api.model
    def _generate_token(self, file_path):
        """Génère un token HMAC sécurisé unique pour chaque fichier."""
        secret = self.env['ir.config_parameter'].sudo().get_param(
            'database.secret', default='odoo-secret'
        )
        return hmac.new(
            secret.encode(),
            file_path.encode(),
            digestmod=hashlib.sha256,
        ).hexdigest()

    @api.model
    def _generate_archive_token(self, records):
        payload = '|'.join(
            '%s:%s' % (record.id, record.download_token or '')
            for record in records.sorted('id')
        )
        secret = self.env['ir.config_parameter'].sudo().get_param(
            'database.secret', default='odoo-secret'
        )
        return hmac.new(secret.encode(), payload.encode(), digestmod=hashlib.sha256).hexdigest()
