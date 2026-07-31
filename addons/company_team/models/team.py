from odoo import models, fields

class CompanyTeam(models.Model):
    _name = "company.team"
    _description = "Company team"


    name = fields.Char(
        string="Nom de l'équipe",
        required=True
    )

    description = fields.Text(
        string="Description"
    )

    active = fields.Boolean(
        string="Active",
        default=True
    )

    creation_date = fields.Date(
        string="Date de création"
    )