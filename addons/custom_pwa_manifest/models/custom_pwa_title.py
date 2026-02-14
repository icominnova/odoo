from odoo import models, fields, api

class CustomPWATitle(models.Model):
    _name = 'custom.pwa.title'
    _description = 'Titre de l\'onglet PWA'

    name = fields.Char(string="Titre de l'onglet", required=True)

    @api.model
    def get_current_title(self):
        # Retourne le titre actif (le plus récent)
        record = self.search([], order='id desc', limit=1)
        return record.name if record else 'Mon Application'
