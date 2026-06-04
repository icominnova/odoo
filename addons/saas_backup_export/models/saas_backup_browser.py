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


class SaasBackupBrowser(models.TransientModel):
    _name = 'saas.backup.browser'
    _description = 'Parcourir le dossier de backups'

    client_folder = fields.Selection(selection='_get_client_folders', string='Base')
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

    def action_load_files(self):
        """Charge les fichiers .zip du dossier sélectionné dans les lignes."""
        if not self.client_folder:
            raise UserError(_('Veuillez choisir une base à parcourir.'))
        config = self.env['saas.backup.config'].search([], limit=1)
        base = config.base_path.rstrip('/') if config else '/opt/odoo/Odoo-SAAS-Data'
        folder = os.path.join(base, self.client_folder)
        if not os.path.isdir(folder):
            raise UserError(_('Le dossier %s n\'existe pas sur le serveur.') % folder)

        # vider les lignes existantes
        self.lines.unlink()

        for filename in sorted(os.listdir(folder)):
            if not filename.lower().endswith('.zip'):
                continue
            full_path = os.path.join(folder, filename)
            try:
                stat = os.stat(full_path)
            except OSError:
                continue
            size_mb = stat.st_size / (1024 * 1024)
            backup_date = datetime.fromtimestamp(stat.st_mtime)
            self.env['saas.backup.browser.line'].create({
                'wizard_id': self.id,
                'name': filename,
                'full_path': full_path,
                'file_size_mb': size_mb,
                'backup_date': backup_date,
                'selected': True,
            })
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
                'client_name': self.client_folder,
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
