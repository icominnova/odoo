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
    saas_auto_backup = fields.Boolean(string='Sauvegarde auto')
    saas_backup_interval_number = fields.Integer(
        string='Tous les',
        default=1,
    )
    saas_backup_interval_type = fields.Selection(
        selection=[
            ('days', 'Jour(s)'),
            ('weeks', 'Semaine(s)'),
            ('months', 'Mois'),
        ],
        string='Période',
        default='days',
    )
    saas_backup_time = fields.Float(
        string='Heure de sauvegarde',
        default=2.0,
    )
    saas_next_backup_datetime = fields.Datetime(string='Prochaine sauvegarde')
    saas_backup_retention = fields.Integer(
        string='Backups à garder',
        default=5,
    )
    saas_last_backup_datetime = fields.Datetime(string='Dernière sauvegarde', readonly=True)
    saas_last_backup_state = fields.Selection([
        ('success', 'Succès'),
        ('failed', 'Échec'),
    ], string='Dernier état', readonly=True)
    saas_last_backup_message = fields.Text(string='Dernier message', readonly=True)

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
        self._load_schedule_from_process()

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
        self._write_schedule_to_process(recompute_next=True)
        self.backup_process_id._saas_log_event(
            'schedule_recomputed',
            state='info',
            scheduled_datetime=self.backup_process_id.saas_next_backup_datetime,
            message=_('Prochaine sauvegarde recalculée depuis l’écran Gérer les backups.'),
        )
        self._load_schedule_from_process()
        return self._reopen()

    def action_save_auto_backup_schedule(self):
        if not self.backup_process_id:
            raise UserError(_('Veuillez choisir un Backup Process.'))
        self._write_schedule_to_process()
        self.backup_process_id._saas_log_event(
            'schedule_saved',
            state='info',
            scheduled_datetime=self.backup_process_id.saas_next_backup_datetime,
            message=_(
                "Programmation enregistrée : tous les %(number)s %(period)s à %(time).2f, rétention %(retention)s.",
                number=self.backup_process_id.saas_backup_interval_number,
                period=self.backup_process_id.saas_backup_interval_type,
                time=self.backup_process_id.saas_backup_time,
                retention=self.backup_process_id.saas_backup_retention,
            ),
        )
        self._load_schedule_from_process()
        return self._reopen()

    def action_run_due_auto_backups(self):
        if self.backup_process_id:
            self._write_schedule_to_process(recompute_past=False)
            self.backup_process_id._saas_log_event(
                'manual_due_check',
                state='info',
                scheduled_datetime=self.backup_process_id.saas_next_backup_datetime,
                message=_('Vérification manuelle des sauvegardes dues lancée depuis Gérer les backups.'),
            )
        self.env['backup.process'].saas_run_due_auto_backups()
        self._load_schedule_from_process()
        return self._reopen()

    def _load_schedule_from_process(self):
        process = self.backup_process_id
        if not process:
            self.saas_auto_backup = False
            self.saas_backup_interval_number = 1
            self.saas_backup_interval_type = 'days'
            self.saas_backup_time = 2.0
            self.saas_next_backup_datetime = False
            self.saas_backup_retention = 5
            self.saas_last_backup_datetime = False
            self.saas_last_backup_state = False
            self.saas_last_backup_message = False
            return

        self.saas_auto_backup = process.saas_auto_backup
        self.saas_backup_interval_number = process.saas_backup_interval_number or 1
        self.saas_backup_interval_type = process.saas_backup_interval_type or 'days'
        self.saas_backup_time = process.saas_backup_time or 2.0
        self.saas_next_backup_datetime = process.saas_next_backup_datetime
        self.saas_backup_retention = process.saas_backup_retention
        self.saas_last_backup_datetime = process.saas_last_backup_datetime
        self.saas_last_backup_state = process.saas_last_backup_state
        self.saas_last_backup_message = process.saas_last_backup_message

    def _write_schedule_to_process(self, recompute_next=False, recompute_past=True):
        self.ensure_one()
        now = fields.Datetime.now()
        values = {
            'saas_auto_backup': self.saas_auto_backup,
            'saas_backup_interval_number': self.saas_backup_interval_number or 1,
            'saas_backup_interval_type': self.saas_backup_interval_type or 'days',
            'saas_backup_time': self.saas_backup_time or 0.0,
            'saas_backup_retention': self.saas_backup_retention,
        }
        next_backup = self.saas_next_backup_datetime
        if self.saas_auto_backup:
            self.backup_process_id.write(values)
            if recompute_next or not next_backup or (recompute_past and next_backup <= now):
                next_backup = self.backup_process_id._saas_next_datetime(now)
            self.backup_process_id.write({'saas_next_backup_datetime': next_backup})
        else:
            values['saas_next_backup_datetime'] = False
            self.backup_process_id.write(values)

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
