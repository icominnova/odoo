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
    full_path = fields.Char(string='Chemin complet')
    file_size_mb = fields.Float(string='Taille (Mo)', digits=(16, 2))
    backup_date = fields.Datetime(string='Date de sauvegarde')
    selected = fields.Boolean(string='Sélectionner', default=True)
    source = fields.Selection([('local', 'Local'), ('filestore', 'Filestore')], string='Source', default='local')
    attachment_id = fields.Many2one('ir.attachment', string='Attachment')


class SaasBackupBrowser(models.TransientModel):
    _name = 'saas.backup.browser'
    _description = 'Parcourir le dossier de backups'

    client_folder = fields.Selection(selection='_get_client_folders', string='Base')
    recursive = fields.Boolean(string='Parcourir récursivement', default=False)
    include_filestore = fields.Boolean(string='Inclure le filestore', default=False)
    lines = fields.One2many('saas.backup.browser.line', 'wizard_id', string='Fichiers')

    def _get_client_folders(self):
        config = self.env['saas.backup.config'].search([], limit=1)
        base = config.base_path.rstrip('/') if config else '/opt/odoo/Odoo-SAAS-Data'
        try:
            entries = sorted(os.listdir(base))
        except Exception:
            return []
        choices = []
        for name in entries:
            path = os.path.join(base, name)
            if os.path.isdir(path):
                choices.append((name, name))
        return choices

    def _add_local_file(self, full_path, client_name=None):
        try:
            stat = os.stat(full_path)
        except OSError:
            return False
        name = os.path.basename(full_path)
        size_mb = stat.st_size / (1024 * 1024)
        backup_date = datetime.fromtimestamp(stat.st_mtime)
        self.env['saas.backup.browser.line'].create({
            'wizard_id': self.id,
            'name': name,
            'full_path': full_path,
            'file_size_mb': size_mb,
            'backup_date': backup_date,
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
            'full_path': full_path,
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
        config = self.env['saas.backup.config'].search([], limit=1)
        base = config.base_path.rstrip('/') if config else '/opt/odoo/Odoo-SAAS-Data'

        # vider les lignes existantes
        self.lines.unlink()

        # parcourir le dossier local (récursif si demandé)
        if self.client_folder:
            folder = os.path.join(base, self.client_folder)
            if not os.path.isdir(folder):
                raise UserError(_('Le dossier %s n\'existe pas sur le serveur.') % folder)
            if self.recursive:
                for root, dirs, files in os.walk(folder):
                    for filename in sorted(files):
                        if not filename.lower().endswith('.zip'):
                            continue
                        full_path = os.path.join(root, filename)
                        self._add_local_file(full_path)
            else:
                for filename in sorted(os.listdir(folder)):
                    if not filename.lower().endswith('.zip'):
                        continue
                    full_path = os.path.join(folder, filename)
                    self._add_local_file(full_path)

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

        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }

    def action_import_selected(self):
        """Crée des enregistrements `saas.backup.file` pour les fichiers sélectionnés."""
        created = 0
        for line in self.lines.filtered(lambda l: l.selected):
            existing = self.env['saas.backup.file'].search([('file_path', '=', line.full_path)], limit=1)
            if existing:
                continue
            token = self.env['saas.backup.file']._generate_token(line.full_path)
            self.env['saas.backup.file'].create({
                'name': line.name,
                'client_name': self.client_folder or (line.attachment_id.res_model if line.attachment_id else 'Filestore'),
                'file_path': line.full_path,
                'file_size_mb': line.file_size_mb,
                'backup_date': line.backup_date,
                'state': 'available',
                'download_token': token,
            })
            created += 1
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Import terminé'),
                'message': _('%s fichier(s) importé(s).') % created,
                'type': 'success',
            },
        }
