# -*- coding: utf-8 -*-
import logging
from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class BackupProcess(models.Model):
    _inherit = 'backup.process'

    saas_auto_backup = fields.Boolean(string='Sauvegarde auto')
    saas_backup_interval_number = fields.Integer(
        string='Tous les',
        default=1,
        help="Nombre de périodes entre deux sauvegardes automatiques.",
    )
    saas_backup_interval_type = fields.Selection([
        ('days', 'Jour(s)'),
        ('weeks', 'Semaine(s)'),
        ('months', 'Mois'),
    ], string='Période', default='days')
    saas_backup_time = fields.Float(
        string='Heure de sauvegarde',
        default=2.0,
        help="Heure serveur à laquelle lancer la sauvegarde automatique.",
    )
    saas_next_backup_datetime = fields.Datetime(string='Prochaine sauvegarde')
    saas_backup_retention = fields.Integer(
        string='Backups à garder',
        default=5,
        help="Nombre maximum de backups ZIP à conserver pour ce process. 0 désactive la suppression automatique.",
    )
    saas_last_backup_datetime = fields.Datetime(string='Dernière sauvegarde', readonly=True)
    saas_last_backup_state = fields.Selection([
        ('success', 'Succès'),
        ('failed', 'Échec'),
    ], string='Dernier état', readonly=True)
    saas_last_backup_message = fields.Text(string='Dernier message', readonly=True)
    saas_process_database_name = fields.Char(
        string='Base',
        compute='_compute_saas_process_info',
    )
    saas_process_storage_path = fields.Char(
        string='Storage Path',
        compute='_compute_saas_process_info',
    )

    def _compute_saas_process_info(self):
        for process in self:
            process.saas_process_database_name = process._saas_get_process_value((
                'database_name',
                'db_name',
                'database',
                'client_db_name',
            ))
            process.saas_process_storage_path = process._saas_get_process_value((
                'storage_path',
                'backup_path',
                'path',
                'local_path',
            ))

    @api.onchange('saas_auto_backup', 'saas_backup_interval_number', 'saas_backup_interval_type', 'saas_backup_time')
    def _onchange_saas_schedule(self):
        for process in self:
            if process.saas_auto_backup and not process.saas_next_backup_datetime:
                process.saas_next_backup_datetime = process._saas_next_datetime(fields.Datetime.now())

    @api.constrains('saas_backup_interval_number', 'saas_backup_time', 'saas_backup_retention')
    def _check_saas_schedule_values(self):
        for process in self:
            if process.saas_backup_interval_number < 1:
                raise ValidationError(_("La période doit être supérieure ou égale à 1."))
            if process.saas_backup_time < 0 or process.saas_backup_time >= 24:
                raise ValidationError(_("L'heure de sauvegarde doit être comprise entre 00:00 et 23:59."))
            if process.saas_backup_retention < 0:
                raise ValidationError(_("Le nombre de backups à garder ne peut pas être négatif."))

    def action_saas_compute_next_backup(self):
        for process in self:
            process.saas_next_backup_datetime = process._saas_next_datetime(fields.Datetime.now())
        return True

    def action_saas_disable_auto_backup(self):
        for process in self:
            scheduled_datetime = process.saas_next_backup_datetime
            process.write({
                'saas_auto_backup': False,
                'saas_next_backup_datetime': False,
            })
            process._saas_log_event(
                'schedule_disabled',
                state='info',
                scheduled_datetime=scheduled_datetime,
                message=_('Programmation automatique désactivée.'),
            )
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    @api.model
    def saas_run_due_auto_backups(self):
        now = fields.Datetime.now()
        processes = self.sudo().search([
            ('saas_auto_backup', '=', True),
            '|',
            ('saas_next_backup_datetime', '=', False),
            ('saas_next_backup_datetime', '<=', now),
        ])
        backup_model = self.env['saas.backup.file'].sudo()
        for process in processes:
            scheduled_datetime = process.saas_next_backup_datetime
            process._saas_log_event(
                'auto_started',
                state='running',
                scheduled_datetime=scheduled_datetime,
                message=_('Sauvegarde automatique démarrée.'),
            )
            try:
                backup = backup_model.action_create_backup_for_process(process)
                backup_model._apply_process_retention(process)
                next_backup_datetime = process._saas_next_datetime(now)
                process.write({
                    'saas_last_backup_datetime': now,
                    'saas_last_backup_state': 'success',
                    'saas_last_backup_message': _('Backup créé : %s') % backup.name,
                    'saas_next_backup_datetime': next_backup_datetime,
                })
                process._saas_log_event(
                    'auto_success',
                    state='success',
                    backup=backup,
                    scheduled_datetime=scheduled_datetime,
                    message=_(
                        "Backup créé : %(backup)s. Prochaine sauvegarde : %(next)s",
                        backup=backup.name,
                        next=next_backup_datetime,
                    ),
                )
            except Exception as error:
                _logger.exception(
                    "Erreur lors de la sauvegarde automatique du process %s",
                    process.display_name,
                )
                process.write({
                    'saas_last_backup_datetime': now,
                    'saas_last_backup_state': 'failed',
                    'saas_last_backup_message': str(error),
                })
                process._saas_log_event(
                    'auto_failed',
                    state='failed',
                    scheduled_datetime=scheduled_datetime,
                    message=str(error),
                )
        return True

    def _saas_next_datetime(self, from_dt):
        self.ensure_one()
        interval_number = max(self.saas_backup_interval_number or 1, 1)
        hour = int(self.saas_backup_time or 0.0)
        minute = int(round(((self.saas_backup_time or 0.0) - hour) * 60))
        if minute >= 60:
            hour += 1
            minute = 0
        hour = max(0, min(hour, 23))

        candidate = from_dt.replace(hour=hour, minute=minute, second=0, microsecond=0)
        step = self._saas_schedule_step(interval_number)
        while candidate <= from_dt:
            candidate += step
        return candidate

    def _saas_schedule_step(self, interval_number):
        self.ensure_one()
        if self.saas_backup_interval_type == 'weeks':
            return timedelta(weeks=interval_number)
        if self.saas_backup_interval_type == 'months':
            return relativedelta(months=interval_number)
        return timedelta(days=interval_number)

    def _saas_get_process_value(self, field_names):
        self.ensure_one()
        for field_name in field_names:
            if field_name not in self._fields:
                continue
            value = self[field_name]
            if hasattr(value, 'display_name'):
                return value.display_name
            return value
        return False

    def _saas_log_event(self, event_type, state='info', message=False, backup=False, scheduled_datetime=False):
        self.ensure_one()
        return self.env['saas.backup.log'].sudo().create({
            'name': self._saas_log_name(event_type, state),
            'backup_process_id': self.id,
            'backup_file_id': backup.id if backup else False,
            'database_name': self._saas_get_process_value((
                'database_name',
                'db_name',
                'database',
                'client_db_name',
            )),
            'event_type': event_type,
            'state': state,
            'scheduled_datetime': scheduled_datetime or self.saas_next_backup_datetime,
            'execution_datetime': fields.Datetime.now(),
            'message': message,
        })

    def _saas_log_name(self, event_type, state):
        labels = dict(self.env['saas.backup.log']._fields['event_type'].selection)
        state_labels = dict(self.env['saas.backup.log']._fields['state'].selection)
        return '%s - %s' % (
            labels.get(event_type, event_type),
            state_labels.get(state, state),
        )
