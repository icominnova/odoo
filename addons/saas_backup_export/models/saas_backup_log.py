# -*- coding: utf-8 -*-
from odoo import fields, models


class SaasBackupLog(models.Model):
    _name = 'saas.backup.log'
    _description = 'Historique des sauvegardes SaaS'
    _order = 'create_date desc, id desc'

    name = fields.Char(string='Résumé', required=True)
    backup_process_id = fields.Many2one(
        'backup.process',
        string='Backup Process',
        index=True,
        ondelete='set null',
    )
    backup_file_id = fields.Many2one(
        'saas.backup.file',
        string='Fichier backup',
        index=True,
        ondelete='set null',
    )
    database_name = fields.Char(string='Base', index=True)
    event_type = fields.Selection([
        ('schedule_saved', 'Programmation enregistrée'),
        ('schedule_recomputed', 'Prochaine sauvegarde recalculée'),
        ('manual_due_check', 'Lancement manuel des sauvegardes dues'),
        ('auto_started', 'Sauvegarde automatique démarrée'),
        ('auto_success', 'Sauvegarde automatique réussie'),
        ('auto_failed', 'Sauvegarde automatique échouée'),
    ], string='Événement', required=True, index=True)
    state = fields.Selection([
        ('info', 'Information'),
        ('running', 'En cours'),
        ('success', 'Succès'),
        ('failed', 'Échec'),
    ], string='État', default='info', required=True, index=True)
    scheduled_datetime = fields.Datetime(string='Date programmée')
    execution_datetime = fields.Datetime(string='Date exécution', default=fields.Datetime.now)
    message = fields.Text(string='Message')
