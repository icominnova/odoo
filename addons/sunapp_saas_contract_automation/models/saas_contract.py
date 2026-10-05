from odoo import api, models


class SaasContract(models.Model):
    _inherit = "saas.contract"

    @api.model
    def client_creation_cron_action(self):
        """
        Désactive le provisioning automatique Webkul.

        Chez SunApp, le devis prépare le contrat et la fiche saas.client.
        La création de la base et du conteneur reste exclusivement
        déclenchée par la confirmation manuelle du contrat SaaS.
        """
        return []
