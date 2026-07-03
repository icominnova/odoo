from odoo import _, models


class SaasClient(models.Model):
    _inherit = "saas.client"

    def action_open_bulk_restart_wizard(self):
        self._check_bulk_restart_access()
        return {
            "type": "ir.actions.act_window",
            "name": _("Restart SaaS Clients"),
            "res_model": "saas.bulk.restart.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                **self.env.context,
                "default_client_ids": [(6, 0, self.ids)],
            },
        }

    def _check_bulk_restart_access(self):
        if hasattr(self, "check_access"):
            self.check_access("write")
            return
        self.check_access_rights("write")
        self.check_access_rule("write")
