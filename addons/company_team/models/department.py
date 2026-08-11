from odoo import models, fields

class CompanyDepartment(models.Model):
    _name = "company.department"
    _description = "Company Department"

    name = fields.Char(
        string="Nom",
        required=True
    )

    description = fields.Text(
        string="Description",
    )

    active = fields.Boolean(
        string="Active",
        default=True
    )

    creation_date = fields.Date(
        string="Date de création",
    )

    employee_ids = fields.One2many(
        "company.employee",
        "department_id",
        string="Employés"
    )
