from odoo import fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    sunapp_saas_domain_name = fields.Char(
        string="Nom de domaine SaaS",
        copy=False,
        index=True,
    )
