from odoo import models, fields

class CustomPWAAppInfo(models.Model):
    _name = 'custom.pwa.appinfo'
    _description = "Infos PWA (nom, images, screenshots, manifest)"

    name = fields.Char(string="Nom de l'application", required=True)
    description = fields.Text(string="Description de l'application")
    background_color = fields.Char(string="Couleur de fond", default="#FFFFFF")
    theme_color = fields.Char(string="Couleur du thème", default="#000000")
    def action_reset_colors(self):
            for rec in self:
                rec.background_color = "#FFFFFF"
                rec.theme_color = "#000000"