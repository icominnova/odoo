# -*- coding: utf-8 -*-
import os
from datetime import datetime

from odoo import fields, models, _
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

    client_folder = fields.Selection(selection='_get_client_folders', string='Base')
    recursive = fields.Boolean(string='Parcourir récursivement', default=True)
    include_filestore = fields.Boolean(string='Inclure le filestore', default=False)
    lines = fields.One2many('saas.backup.browser.line', 'wizard_id', string='Fichiers')

    def _get_client_folders(self):
        try:
            return self.env['saas.backup.file']._iter_client_folders()
        except UserError:
            return []

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
        if not self.client_folder and not self.include_filestore:
            raise UserError(_('Veuillez choisir une base à parcourir ou cocher Inclure le filestore.'))
        backup_file = self.env['saas.backup.file']
        base = backup_file._get_base_path()

        # vider les lignes existantes
        self.lines.unlink()

        # parcourir le dossier local (récursif si demandé)
        if self.client_folder:
            for vals in backup_file._iter_backup_files(
                base,
                client_folder=self.client_folder,
                recursive=self.recursive,
            ):
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
                # si client_folder spécifiée, on tente de limiter par res_model/res_name? non
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
            'client_name': line.client_name or self.client_folder or 'Filestore',
            'file_path': line.full_path,
            'file_size_mb': line.file_size_mb,
            'backup_date': line.backup_date,
            'relative_path': line.relative_path or line.name,
            'state': 'available',
        }
        return self.env['saas.backup.file']._upsert_backup_file(vals)

    def _reopen(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Ajouter des backups'),
            'res_model': self._name,
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'current',
        }
