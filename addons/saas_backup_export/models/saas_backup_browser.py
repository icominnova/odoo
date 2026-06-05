# -*- coding: utf-8 -*-
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
    source = fields.Selection([('backup', 'Backup ZIP')], string='Source', default='backup')
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
    lines = fields.One2many('saas.backup.browser.line', 'wizard_id', string='Fichiers')
    saas_auto_backup = fields.Boolean(
        string='Sauvegarde auto',
        related='backup_process_id.saas_auto_backup',
        readonly=False,
    )
    saas_backup_interval_number = fields.Integer(
        string='Tous les',
        related='backup_process_id.saas_backup_interval_number',
        readonly=False,
    )
    saas_backup_interval_type = fields.Selection(
        related='backup_process_id.saas_backup_interval_type',
        readonly=False,
    )
    saas_backup_time = fields.Float(
        string='Heure de sauvegarde',
        related='backup_process_id.saas_backup_time',
        readonly=False,
    )
    saas_next_backup_datetime = fields.Datetime(
        string='Prochaine sauvegarde',
        related='backup_process_id.saas_next_backup_datetime',
        readonly=False,
    )
    saas_backup_retention = fields.Integer(
        string='Backups à garder',
        related='backup_process_id.saas_backup_retention',
        readonly=False,
    )
    saas_last_backup_datetime = fields.Datetime(
        string='Dernière sauvegarde',
        related='backup_process_id.saas_last_backup_datetime',
        readonly=True,
    )
    saas_last_backup_state = fields.Selection(
        related='backup_process_id.saas_last_backup_state',
        readonly=True,
    )
    saas_last_backup_message = fields.Text(
        string='Dernier message',
        related='backup_process_id.saas_last_backup_message',
        readonly=True,
    )

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

    def _add_backup_file(self, backup):
        self.env['saas.backup.browser.line'].create({
            'wizard_id': self.id,
            'name': backup.name,
            'client_name': backup.database_name or backup.client_name,
            'full_path': backup.file_path,
            'relative_path': backup.relative_path,
            'file_size_mb': backup.file_size_mb,
            'backup_date': backup.backup_date,
            'selected': True,
            'source': 'backup',
        })
        return True

    def action_load_files(self):
        """Charge les ZIP complets déjà stockés pour ce Backup Process."""
        if not self.backup_process_id:
            raise UserError(_('Veuillez choisir un Backup Process.'))

        self.lines.unlink()
        self._refresh_process_info()

        backups = self.env['saas.backup.file'].action_scan_process_backups(self.backup_process_id)
        for backup in backups:
            self._add_backup_file(backup)

        line_count = self.env['saas.backup.browser.line'].search_count([('wizard_id', '=', self.id)])
        if not line_count:
            raise UserError(_('Aucun backup ZIP trouvé pour cette sélection. Lancez une sauvegarde maintenant.'))

        return self._reopen()

    def action_create_backup_now(self):
        if not self.backup_process_id:
            raise UserError(_('Veuillez choisir un Backup Process.'))

        self._refresh_process_info()
        backup = self.env['saas.backup.file'].action_create_backup_for_process(self.backup_process_id)
        self.lines.unlink()
        self._add_backup_file(backup)
        return self._reopen()

    def action_export_selected(self):
        selected_lines = self.lines.filtered(lambda line: line.selected)
        if not selected_lines:
            raise UserError(_('Aucun fichier selectionne.'))

        records = self.env['saas.backup.file']
        for line in selected_lines:
            record, _was_created = self._upsert_line(line)
            records |= record
        return records.action_download_archive()

    def action_delete_selected(self):
        selected_lines = self.lines.filtered(lambda line: line.selected)
        if not selected_lines:
            raise UserError(_('Aucun fichier selectionne.'))

        records = self.env['saas.backup.file']
        for line in selected_lines:
            record, _was_created = self._upsert_line(line)
            records |= record

        records.action_delete_backup()
        self.lines.unlink()
        if self.backup_process_id:
            backups = self.env['saas.backup.file'].action_scan_process_backups(self.backup_process_id)
            for backup in backups:
                self._add_backup_file(backup)
        return self._reopen()

    def action_recompute_next_backup(self):
        if not self.backup_process_id:
            raise UserError(_('Veuillez choisir un Backup Process.'))
        self.backup_process_id.action_saas_compute_next_backup()
        return self._reopen()

    def _upsert_line(self, line):
        vals = {
            'name': line.name,
            'backup_process_id': self.backup_process_id.id,
            'database_name': line.client_name or self.database_name,
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

    def _reopen(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Gérer les backups'),
            'res_model': self._name,
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'current',
        }
