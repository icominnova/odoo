import logging
import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class SaasBulkRestartWizard(models.TransientModel):
    _name = "saas.bulk.restart.wizard"
    _description = "Bulk restart SaaS clients"

    client_ids = fields.Many2many(
        "saas.client",
        string="SaaS Clients",
        required=True,
    )
    client_count = fields.Integer(
        string="Clients",
        compute="_compute_client_count",
    )

    @api.depends("client_ids")
    def _compute_client_count(self):
        for wizard in self:
            wizard.client_count = len(wizard.client_ids)

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        if values.get("client_ids"):
            return values

        if self.env.context.get("active_model") == "saas.client":
            active_ids = self.env.context.get("active_ids") or []
            if active_ids:
                values["client_ids"] = [(6, 0, active_ids)]
            elif self.env.context.get("active_domain"):
                clients = self.env["saas.client"].search(self.env.context["active_domain"])
                values["client_ids"] = [(6, 0, clients.ids)]
        return values

    def action_restart_clients(self):
        self.ensure_one()
        clients = self.client_ids
        if not clients:
            raise UserError(_("Select at least one SaaS client to restart."))

        clients._check_bulk_restart_access()
        restart_method_name = self._find_restart_method_name(clients)

        success_clients = self.env["saas.client"]
        failed = []
        for client in clients:
            try:
                with self.env.cr.savepoint():
                    getattr(client, restart_method_name)()
                    success_clients |= client
                    if hasattr(client, "message_post"):
                        client.message_post(
                            body=_("Bulk restart requested by %s.") % self.env.user.display_name
                        )
            except Exception as error:
                _logger.exception("Bulk restart failed for SaaS client %s", client.display_name)
                failed.append((client.display_name, str(error)))

        message = _("%s SaaS client(s) restarted.") % len(success_clients)
        if failed:
            message += "\n" + _("%s client(s) failed:") % len(failed)
            message += "\n" + "\n".join("- %s: %s" % item for item in failed)

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Bulk Restart"),
                "message": message,
                "type": "warning" if failed else "success",
                "sticky": bool(failed),
                "next": {"type": "ir.actions.act_window_close"},
            },
        }

    def _find_restart_method_name(self, clients):
        candidate_names = (
            "action_restart",
            "button_restart",
            "restart",
            "restart_server",
            "restart_client",
            "restart_saas",
            "restart_instance",
            "action_restart_server",
            "action_restart_client",
            "action_restart_instance",
            "action_restart_container",
            "server_restart",
            "restart_container",
            "restart_odoo",
            "action_restart_odoo",
        )
        for method_name in candidate_names:
            method = getattr(clients[:1], method_name, None)
            if callable(method):
                return method_name

        for method_name in self._find_restart_methods_from_views():
            method = getattr(clients[:1], method_name, None)
            if callable(method):
                return method_name

        raise UserError(
            _(
                "No restart method was found on saas.client. "
                "Open the original SaaS Kit form view and check the technical name of the Restart button."
            )
        )

    def _find_restart_methods_from_views(self):
        views = self.env["ir.ui.view"].sudo().search([
            ("model", "=", "saas.client"),
            ("arch_db", "ilike", "Restart"),
        ])
        method_names = []
        for view in views:
            arch = str(view.arch_db or "")
            for button in re.findall(r"<button\b[^>]*>", arch, flags=re.IGNORECASE):
                if not re.search(r"\bstring=['\"]Restart['\"]", button, flags=re.IGNORECASE):
                    continue
                match = re.search(r"\bname=['\"]([^'\"]+)['\"]", button)
                if match:
                    method_names.append(match.group(1))
        return method_names
