from odoo import models, fields

class CompanyTeam(models.Model):
    _name = "company.team"
    _description = "Company team"


    name = fields.Char(
        string="Nom Equipe",
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

    department_id = fields.Many2one(
        "company.department",
        string="Département",
        required=True
    )