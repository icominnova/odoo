# -*- coding: utf-8 -*-
import os
from datetime import datetime

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class SaasBackupBrowserLine(models.TransientModel):
    _name = 'saas.backup.browser.line'
    _description = 'Ligne temporaire pour parcourir les backups'

    wizard_id = fields.Many2one('saas.backup.browser', ondelete='cascade')
    name = fields.Char(string='Nom du fichier')
    client_name = fields.Char(string='Base')
    full_path = fields.Char(string='Chemin complet')
    relative_path = fields.Char(string='Chemin relatif')
    file_size_mb = fields.Float(string='Taille (Mo)', digits=(16, 2))
    backup_date = fields.Datetime(string='Date de sauvegarde')
    selected = fields.Boolean(string='Sélectionner', default=True)
    source = fields.Selection([('local', 'Local'), ('filestore', 'Filestore')], string='Source', default='local')
    attachment_id = fields.Many2one('ir.attachment', string='Attachment')


class SaasBackupBrowser(models.TransientModel):
    _name = 'saas.backup.browser'
    _description = 'Parcourir le dossier de backups'

    backup_process_id = fields.Many2one(
        'backup.process',
        string='Backup Process',
        help="Processus de sauvegarde SaaS existant. Le module utilisera son Storage Path.",
    )
    database_name = fields.Char(string='Database Name', readonly=True)
    storage_path = fields.Char(string='Storage Path', readonly=True)
    recursive = fields.Boolean(string='Parcourir récursivement', default=True)
    include_filestore = fields.Boolean(string='Inclure le filestore', default=False)
    lines = fields.One2many('saas.backup.browser.line', 'wizard_id', string='Fichiers')

    @api.onchange('backup_process_id')
    def _onchange_backup_process_id(self):
        self.lines = [(5, 0, 0)]
        self.database_name = self._get_backup_process_value(
            self.backup_process_id,
            ('database_name', 'db_name', 'database', 'client_db_name'),
        )
        self.storage_path = self._get_backup_process_value(
            self.backup_process_id,
            ('storage_path', 'backup_path', 'path', 'local_path'),
        )

    def _add_local_file(self, vals):
        self.env['saas.backup.browser.line'].create({
            'wizard_id': self.id,
            'name': vals['name'],
            'client_name': vals['client_name'],
            'full_path': vals['file_path'],
            'relative_path': vals['relative_path'],
            'file_size_mb': vals['file_size_mb'],
            'backup_date': vals['backup_date'],
            'selected': True,
            'source': 'local',
        })
        return True

    def _add_filestore_attachment(self, attach):
        store_fname = attach.store_fname
        if not store_fname:
            return False
        try:
            full_path = self.env['ir.attachment']._full_path(store_fname)
        except Exception:
            return False
        if not os.path.isfile(full_path):
            return False
        name = attach.datas_fname or attach.name or os.path.basename(full_path)
        stat = os.stat(full_path)
        size_mb = stat.st_size / (1024 * 1024)
        backup_date = datetime.fromtimestamp(stat.st_mtime)
        self.env['saas.backup.browser.line'].create({
            'wizard_id': self.id,
            'name': name,
            'client_name': attach.res_name or attach.res_model or 'Filestore',
            'full_path': full_path,
            'relative_path': name,
            'file_size_mb': size_mb,
            'backup_date': backup_date,
            'selected': True,
            'source': 'filestore',
            'attachment_id': attach.id,
        })
        return True

    def action_load_files(self):
        """Charge les fichiers .zip du dossier sélectionné dans les lignes."""
        if not self.backup_process_id and not self.include_filestore:
            raise UserError(_('Veuillez choisir un Backup Process ou cocher Inclure le filestore.'))

        # vider les lignes existantes
        self.lines.unlink()

        if self.backup_process_id:
            self._refresh_process_info()
            for vals in self._iter_process_zip_files():
                self._add_local_file(vals)

        # inclure les fichiers du filestore si demandé
        if self.include_filestore:
            attachments = self.env['ir.attachment'].sudo().search([
                '&', ('store_fname', '!=', False),
                '|', '|',
                ('mimetype', '=', 'application/zip'),
                ('name', 'ilike', '%.zip'),
                ('datas_fname', 'ilike', '%.zip'),
            ])
            for attach in attachments:
                self._add_filestore_attachment(attach)

        line_count = self.env['saas.backup.browser.line'].search_count([('wizard_id', '=', self.id)])
        if not line_count:
            raise UserError(_('Aucun fichier .zip trouve pour cette selection.'))

        return self._reopen()

    def action_import_selected(self):
        """Crée des enregistrements `saas.backup.file` pour les fichiers sélectionnés."""
        imported_records = self.env['saas.backup.file']
        for line in self.lines.filtered(lambda l: l.selected):
            record, _was_created = self._upsert_line(line)
            imported_records |= record

        if imported_records:
            return {
                'type': 'ir.actions.act_window',
                'name': _('Fichiers de sauvegarde importes'),
                'res_model': 'saas.backup.file',
                'view_mode': 'list,form',
                'domain': [('id', 'in', imported_records.ids)],
                'context': {'create': False},
            }

        raise UserError(_('Aucun fichier selectionne.'))

    def action_export_selected(self):
        selected_lines = self.lines.filtered(lambda line: line.selected)
        if not selected_lines:
            raise UserError(_('Aucun fichier selectionne.'))

        records = self.env['saas.backup.file']
        for line in selected_lines:
            record, _was_created = self._upsert_line(line)
            records |= record
        return records.action_download_archive()

    def _upsert_line(self, line):
        vals = {
            'name': line.name,
            'client_name': line.client_name or self.database_name or 'Filestore',
            'file_path': line.full_path,
            'file_size_mb': line.file_size_mb,
            'backup_date': line.backup_date,
            'relative_path': line.relative_path or line.name,
            'state': 'available',
        }
        return self.env['saas.backup.file']._upsert_backup_file(vals)

    def _refresh_process_info(self):
        self.ensure_one()
        self.database_name = self._get_backup_process_value(
            self.backup_process_id,
            ('database_name', 'db_name', 'database', 'client_db_name'),
        )
        self.storage_path = self._get_backup_process_value(
            self.backup_process_id,
            ('storage_path', 'backup_path', 'path', 'local_path'),
        )
        if not self.storage_path:
            raise UserError(_(
                "Impossible de trouver le Storage Path sur le modele backup.process. "
                "Verifiez le nom technique du champ dans le menu développeur."
            ))

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

    def _iter_process_zip_files(self):
        self.ensure_one()
        scan_paths = self._get_process_scan_paths()
        if not scan_paths:
            raise UserError(_(
                "Aucun dossier accessible trouve pour le Storage Path : %s"
            ) % self.storage_path)

        seen_paths = set()
        for scan_path in scan_paths:
            if self.recursive:
                for root, _dirs, files in os.walk(scan_path):
                    for filename in sorted(files, key=str.lower):
                        full_path = os.path.join(root, filename)
                        if filename.lower().endswith('.zip') and full_path not in seen_paths:
                            seen_paths.add(full_path)
                            yield self._file_values_from_path(scan_path, full_path)
            else:
                for filename in sorted(os.listdir(scan_path), key=str.lower):
                    full_path = os.path.join(scan_path, filename)
                    if os.path.isfile(full_path) and filename.lower().endswith('.zip') and full_path not in seen_paths:
                        seen_paths.add(full_path)
                        yield self._file_values_from_path(scan_path, full_path)

    def _get_process_scan_paths(self):
        storage_path = os.path.abspath(os.path.expanduser(self.storage_path or ''))
        candidates = [storage_path]

        if os.path.basename(storage_path.rstrip(os.sep)) == 'data-dir':
            candidates.append(os.path.dirname(storage_path))
        else:
            candidates.append(os.path.join(storage_path, 'data-dir'))

        scan_paths = []
        seen_real_paths = set()
        for candidate in candidates:
            real_path = os.path.realpath(candidate)
            if real_path in seen_real_paths:
                continue
            seen_real_paths.add(real_path)
            if os.path.isdir(real_path):
                scan_paths.append(real_path)
        return scan_paths

    def _file_values_from_path(self, scan_path, full_path):
        stat = os.stat(full_path)
        return {
            'name': os.path.basename(full_path),
            'client_name': self.database_name or self.backup_process_id.display_name,
            'file_path': full_path,
            'relative_path': os.path.relpath(full_path, scan_path),
            'file_size_mb': stat.st_size / (1024 * 1024),
            'backup_date': datetime.fromtimestamp(stat.st_mtime),
            'state': 'available',
        }

    def _reopen(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Ajouter des backups'),
            'res_model': self._name,
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'current',
        }
