# -*- coding: utf-8 -*-
from odoo import fields, models, _


class SaasBackupDashboard(models.Model):
    _name = 'saas.backup.dashboard'
    _description = 'Tableau de bord des backups SaaS'

    name = fields.Char(default='Tableau de bord backups', required=True)
    backup_count = fields.Integer(string='Backups disponibles', compute='_compute_summary')
    auto_process_count = fields.Integer(string='Programmations actives', compute='_compute_summary')
    due_process_count = fields.Integer(string='Sauvegardes dues', compute='_compute_summary')
    failed_log_count = fields.Integer(string='Échecs récents', compute='_compute_summary')
    latest_backup_id = fields.Many2one('saas.backup.file', string='Dernier backup', compute='_compute_summary')
    next_process_id = fields.Many2one('backup.process', string='Prochaine programmation', compute='_compute_summary')
    next_backup_datetime = fields.Datetime(string='Prochaine sauvegarde', compute='_compute_summary')
    cron_active = fields.Boolean(string='Cron actif', compute='_compute_summary')
    cron_nextcall = fields.Datetime(string='Prochaine vérification cron', compute='_compute_summary')
    cron_lastcall = fields.Datetime(string='Dernière vérification cron', compute='_compute_summary')

    def _compute_summary(self):
        BackupFile = self.env['saas.backup.file'].sudo()
        BackupProcess = self.env['backup.process'].sudo()
        BackupLog = self.env['saas.backup.log'].sudo()
        now = fields.Datetime.now()

        backup_count = BackupFile.search_count([('state', '=', 'available')])
        auto_process_count = BackupProcess.search_count([('saas_auto_backup', '=', True)])
        due_process_count = BackupProcess.search_count([
            ('saas_auto_backup', '=', True),
            '|',
            ('saas_next_backup_datetime', '=', False),
            ('saas_next_backup_datetime', '<=', now),
        ])
        failed_log_count = BackupLog.search_count([('state', '=', 'failed')])
        latest_backup = BackupFile.search([('state', '=', 'available')], order='backup_date desc, id desc', limit=1)
        next_process = BackupProcess.search([
            ('saas_auto_backup', '=', True),
            ('saas_next_backup_datetime', '!=', False),
        ], order='saas_next_backup_datetime asc, id asc', limit=1)
        cron = self.env.ref(
            'saas_backup_export.ir_cron_saas_backup_export_auto_backup',
            raise_if_not_found=False,
        )

        for dashboard in self:
            dashboard.backup_count = backup_count
            dashboard.auto_process_count = auto_process_count
            dashboard.due_process_count = due_process_count
            dashboard.failed_log_count = failed_log_count
            dashboard.latest_backup_id = latest_backup
            dashboard.next_process_id = next_process
            dashboard.next_backup_datetime = next_process.saas_next_backup_datetime if next_process else False
            dashboard.cron_active = bool(cron and cron.active)
            dashboard.cron_nextcall = cron.nextcall if cron and 'nextcall' in cron._fields else False
            dashboard.cron_lastcall = cron.lastcall if cron and 'lastcall' in cron._fields else False

    def action_open_backup_wizard(self):
        wizard = self.env['saas.backup.browser'].create({})
        return {
            'type': 'ir.actions.act_window',
            'name': _('Créer ou gérer un backup'),
            'res_model': 'saas.backup.browser',
            'view_mode': 'form',
            'res_id': wizard.id,
            'target': 'current',
        }

    def action_open_backups(self):
        return self.env.ref('saas_backup_export.saas_backup_file_action').read()[0]

    def action_open_schedule(self):
        return self.env.ref('saas_backup_export.saas_backup_active_schedule_action').read()[0]

    def action_open_due_schedule(self):
        now = fields.Datetime.now()
        action = self.env.ref('saas_backup_export.saas_backup_process_schedule_action').read()[0]
        action['name'] = _('Sauvegardes dues')
        action['domain'] = [
            ('saas_auto_backup', '=', True),
            '|',
            ('saas_next_backup_datetime', '=', False),
            ('saas_next_backup_datetime', '<=', now),
        ]
        return action

    def action_open_logs(self):
        return self.env.ref('saas_backup_export.saas_backup_log_action').read()[0]

    def action_clear_logs(self):
        self.env['saas.backup.log'].sudo().search([]).unlink()
        return self.action_open_logs()

    def action_reactivate_cron(self):
        cron = self.env.ref(
            'saas_backup_export.ir_cron_saas_backup_export_auto_backup',
            raise_if_not_found=False,
        )
        if cron:
            cron.sudo().write({
                'active': True,
                'nextcall': fields.Datetime.now(),
                'interval_number': 1,
                'interval_type': 'minutes',
            })
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Cron réactivé'),
                'message': _('La vérification automatique des sauvegardes est planifiée toutes les minutes.'),
                'type': 'success',
                'sticky': False,
            },
        }

    def action_open_failed_logs(self):
        action = self.env.ref('saas_backup_export.saas_backup_log_action').read()[0]
        action['name'] = _('Échecs de sauvegarde')
        action['domain'] = [('state', '=', 'failed')]
        return action

    def action_run_due_auto_backups(self):
        self.env['backup.process'].saas_run_due_auto_backups()
        return self.action_open_logs()
