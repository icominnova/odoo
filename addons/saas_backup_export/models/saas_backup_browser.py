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
    source = fields.Selection([
        ('local', 'Local'),
        ('filestore', 'Filestore'),
        ('folder', 'Dossier'),
    ], string='Source', default='local')
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
            'source': vals.get('source', 'local'),
            'attachment_id': vals.get('attachment_id'),
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
        name = attach.name or os.path.basename(full_path)
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
        """Charge le dossier filestore du Backup Process sélectionné."""
        if not self.backup_process_id and not self.include_filestore:
            raise UserError(_('Veuillez choisir un Backup Process ou cocher Inclure le filestore.'))

        # vider les lignes existantes
        self.lines.unlink()

        if self.backup_process_id:
            self._refresh_process_info()
            self._add_process_filestore_folder()

        # inclure les fichiers du filestore si demandé
        if self.include_filestore:
            attachments = self.env['ir.attachment'].sudo().search([
                '&', ('store_fname', '!=', False),
                '|',
                ('mimetype', '=', 'application/zip'),
                ('name', 'ilike', '%.zip'),
            ])
            for attach in attachments:
                self._add_filestore_attachment(attach)

        line_count = self.env['saas.backup.browser.line'].search_count([('wizard_id', '=', self.id)])
        if not line_count:
            raise UserError(_('Aucun dossier filestore accessible trouve pour cette selection.'))

        return self._reopen()

    def action_import_selected(self):
        """Crée des enregistrements `saas.backup.file` pour les fichiers sélectionnés."""
        if self.lines.filtered(lambda line: line.selected and os.path.isdir(line.full_path)):
            raise UserError(_('Les dossiers filestore doivent être exportés directement, pas ajoutés à la liste des fichiers.'))

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
        folder_lines = selected_lines.filtered(lambda line: os.path.isdir(line.full_path))
        file_lines = selected_lines - folder_lines

        if folder_lines:
            return self._download_browser_lines(selected_lines)

        for line in file_lines:
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

    def _add_process_filestore_folder(self):
        filestore_path = self._get_process_filestore_path()
        if not filestore_path:
            return False

        stat = os.stat(filestore_path)
        self.env['saas.backup.browser.line'].create({
            'wizard_id': self.id,
            'name': 'filestore',
            'client_name': self.database_name or self.backup_process_id.display_name,
            'full_path': filestore_path,
            'relative_path': os.path.basename(filestore_path),
            'file_size_mb': self._get_folder_size_mb(filestore_path),
            'backup_date': datetime.fromtimestamp(stat.st_mtime),
            'selected': True,
            'source': 'folder',
        })
        return True

    def _get_process_filestore_path(self):
        storage_path = os.path.abspath(os.path.expanduser(self.storage_path or ''))
        candidates = []

        if os.path.basename(storage_path.rstrip(os.sep)) == 'data-dir':
            candidates.append(os.path.join(storage_path, 'filestore'))
        else:
            candidates.append(os.path.join(storage_path, 'data-dir', 'filestore'))
            candidates.append(os.path.join(storage_path, 'filestore'))

        if self.database_name:
            for candidate in list(candidates):
                candidates.append(os.path.join(candidate, self.database_name))

        for candidate in candidates:
            real_path = os.path.realpath(candidate)
            if os.path.isdir(real_path):
                return real_path
        return False

    def _get_folder_size_mb(self, folder_path):
        total_size = 0
        for root, _dirs, files in os.walk(folder_path):
            for filename in files:
                full_path = os.path.join(root, filename)
                try:
                    total_size += os.path.getsize(full_path)
                except OSError:
                    continue
        return total_size / (1024 * 1024)

    def _download_browser_lines(self, lines):
        token = self._generate_lines_token(lines)
        ids = ','.join(str(line.id) for line in lines.sorted('id'))
        return {
            'type': 'ir.actions.act_url',
            'url': f'/saas/backup/download_browser_lines?ids={ids}&token={token}',
            'target': 'self',
        }

    def _generate_lines_token(self, lines):
        payload = '|'.join(
            '%s:%s' % (line.id, line.full_path or '')
            for line in lines.sorted('id')
        )
        secret = self.env['ir.config_parameter'].sudo().get_param(
            'database.secret', default='odoo-secret'
        )
        return self.env['saas.backup.file']._generate_token(payload + secret)

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
            return

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

    def _iter_process_backup_files(self):
        seen_paths = set()

        for attach in self._get_process_backup_attachments():
            vals = self._file_values_from_attachment(attach)
            if not vals or vals['file_path'] in seen_paths:
                continue
            seen_paths.add(vals['file_path'])
            yield vals

        for vals in self._iter_process_zip_files():
            if vals['file_path'] in seen_paths:
                continue
            seen_paths.add(vals['file_path'])
            yield vals

    def _get_process_backup_attachments(self):
        Attachment = self.env['ir.attachment'].sudo()
        attachments = Attachment
        process = self.backup_process_id.sudo()

        attachments |= self._search_record_attachments(process)
        attachments |= self._get_attachment_fields(process)

        for record in self._get_process_detail_records(process):
            attachments |= self._search_record_attachments(record)
            attachments |= self._get_attachment_fields(record)

        return attachments.filtered(self._is_backup_attachment)

    def _search_record_attachments(self, record):
        return self.env['ir.attachment'].sudo().search([
            ('res_model', '=', record._name),
            ('res_id', '=', record.id),
            ('store_fname', '!=', False),
        ])

    def _get_attachment_fields(self, record):
        attachments = self.env['ir.attachment'].sudo()
        for field_name, field in record._fields.items():
            if field.type == 'many2one' and field.comodel_name == 'ir.attachment':
                if record[field_name]:
                    attachments |= record[field_name]
            elif field.type in ('many2many', 'one2many') and field.comodel_name == 'ir.attachment':
                if record[field_name]:
                    attachments |= record[field_name]
        return attachments

    def _get_process_detail_records(self, process):
        detail_records = []
        for field_name, field in process._fields.items():
            if field.type not in ('one2many', 'many2many'):
                continue
            marker = '%s %s' % (field_name, field.comodel_name or '')
            marker = marker.lower()
            if not any(token in marker for token in ('backup', 'detail', 'line', 'log')):
                continue
            detail_records.extend(process[field_name])
        return detail_records

    def _is_backup_attachment(self, attach):
        name = (attach.name or '').lower()
        mimetype = (attach.mimetype or '').lower()
        return name.endswith('.zip') or mimetype in (
            'application/zip',
            'application/x-zip-compressed',
            'application/octet-stream',
        )

    def _file_values_from_attachment(self, attach):
        if not attach.store_fname:
            return False
        try:
            full_path = self.env['ir.attachment']._full_path(attach.store_fname)
        except Exception:
            return False
        if not os.path.isfile(full_path):
            return False

        stat = os.stat(full_path)
        return {
            'name': attach.name or os.path.basename(full_path),
            'client_name': self.database_name or self.backup_process_id.display_name,
            'file_path': full_path,
            'relative_path': attach.name or os.path.basename(full_path),
            'file_size_mb': stat.st_size / (1024 * 1024),
            'backup_date': datetime.fromtimestamp(stat.st_mtime),
            'source': 'filestore',
            'attachment_id': attach.id,
            'state': 'available',
        }

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
