from odoo import models, fields

class CustomPWAImage(models.Model):
    _name = 'custom.pwa.image'
    _description = "Image PWA Personnalisée"

    name = fields.Char(string="Nom de l'image", required=True)
    image = fields.Image(string="Image", max_width=256, max_height=256, required=True)
