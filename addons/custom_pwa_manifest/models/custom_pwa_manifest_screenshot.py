from odoo import models, fields

class CustomPWAManifestScreenshot(models.Model):
    _name = 'custom.pwa.manifest.screenshot'
    _description = "Screenshot Manifest PWA"

    name = fields.Char(string="Nom")
    image = fields.Binary(string="Image", attachment=True, required=True)
    sizes = fields.Char(string="Tailles", required=True, help="Ex: 1839x991 ou 860x1746")
    type = fields.Char(string="Type", default="image/png")
    form_factor = fields.Selection([
        ('wide', 'Wide'),
        ('narrow', 'Narrow')
    ], string="Form Factor", required=True)
    label = fields.Char(string="Label", help="Texte affiché sous le screenshot")
