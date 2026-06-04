# -*- coding: utf-8 -*-
from odoo import fields, models


class SaasBackupConfig(models.Model):
    """Configuration globale du module SaaS Backup Export.

    Stocke le chemin racine où se trouvent les dossiers de sauvegarde
    des clients SaaS (ex: /opt/odoo/Odoo-SAAS-Data/).
    """
    _name = 'saas.backup.config'
    _description = 'Configuration Backup SaaS'
    _rec_name = 'base_path'

    base_path = fields.Char(
        string='Dossier racine des backups',
        required=True,
        default='/opt/odoo/Odoo-SAAS-Data/',
        help="Chemin absolu sur le serveur où sont stockés les dossiers de sauvegarde "
             "des clients SaaS. Ex: /opt/odoo/Odoo-SAAS-Data/",
    )
    active = fields.Boolean(default=True)
    note = fields.Text(string='Notes')
