from odoo import models, fields

class CustomPWAManifestImage(models.Model):
    _name = 'custom.pwa.manifest.image'
    _description = "Icônes du manifeste PWA"

    name = fields.Char(string="Nom", required=True)
    image = fields.Image(string="Image", required=True)
    sizes = fields.Char(string="Taille (ex: 192x192)", required=True)
    type = fields.Char(string="Type MIME", default="image/png")
    purpose = fields.Selection([
        ('any', 'any'),
        ('maskable', 'maskable'),
        ('monochrome', 'monochrome')
    ], string="Purpose", default="any")
