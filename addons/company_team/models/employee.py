from odoo import api, fields, models
from odoo.exceptions import ValidationError

class CompanyEmployee(models.Model):
    _name = "company.employee"
    _description = "Company Employee"
    _sql_constraints = [
        (
            'unique_matricule',
            'unique(matricule)',
            'Ce matricule existe déjà !'
        )
    ]

    first_name = fields.Char(
        string="Prénom",
        required=True
    )

    last_name = fields.Char(
        string="Nom",
        required=True
    )

    full_name = fields.Char(
        string="Nom complet",
        compute="_compute_full_name",
        store=True
    )

    matricule = fields.Char(
        string="Matricule",
        readonly=True,
        copy=False
    )

    numero_tel = fields.Char(
        string="Téléphone",
        required=True
    )

    email = fields.Char(
        string="Email",
        required=True
    )

    department_id = fields.Many2one(
        "company.department",
        string="Département"
    )

    team_id = fields.Many2one(
            "company.team",
            string="Équipe"
        )

    role = fields.Char(
        string="Rôle",
        required=True
    )

    attendance = fields.Float(
        string="Assiduité (%)",
    )

    team_name = fields.Char(
        related="team_id.name",
        store=True
    )
    
    @api.constrains("attendance")
    def _check_attendance(self):
        for record in self:
            if record.attendance < 0 or record.attendance > 100:
                raise ValidationError("L'assiduité doit être comprise entre 0 et 100")
        
    @api.constrains("numero_tel")
    def _check_numero_tel(self):
        for record in self:
            if record.numero_tel:
                if not record.numero_tel.isdigit():
                    raise ValidationError("Numéro invalide")

                if len(record.numero_tel) != 8:
                    raise ValidationError("Le numéro doit contenir exatement 8 chiffres")
                
    @api.onchange("attendance")
    def _onchange_attendance(self):
        if self.attendance >= 90:
            self.role="Employé exemplaire"
        else:
            self.role=False

    @api.depends("first_name", "last_name")
    def _compute_full_name(self):
        for record in self:
            record.full_name= f"{record.first_name or ''} {record.last_name or ''}".strip()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("matricule"):
                vals["matricule"] = self.env["ir.sequence"].next_by_code(
                    "company.employee"
                ) or "Nouveau"        
        return super().create(vals_list)
    