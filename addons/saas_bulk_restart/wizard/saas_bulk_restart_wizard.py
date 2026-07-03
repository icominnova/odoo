import logging
import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class SaasBulkRestartWizard(models.TransientModel):
    _name = "saas.bulk.restart.wizard"
    _description = "Bulk SaaS client operations"

    all_clients = fields.Boolean(
        string="All SaaS Clients",
        help="Apply the operation to every client matching the selected filter.",
    )
    state_filter = fields.Selection(
        [
            ("all", "All"),
            ("started", "Started"),
            ("stopped", "Stopped"),
        ],
        string="Filter",
        default="all",
        required=True,
    )

    client_ids = fields.Many2many(
        "saas.client",
        string="SaaS Clients",
    )
    client_count = fields.Integer(
        string="Clients",
        compute="_compute_client_count",
    )
    confirm_delete = fields.Boolean(
        string="I confirm deletion",
        help="Required before deleting clients from the server.",
    )

    @api.depends("client_ids")
    def _compute_client_count(self):
        for wizard in self:
            wizard.client_count = len(wizard._get_operation_clients())

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

    @api.onchange("all_clients", "state_filter")
    def _onchange_all_clients(self):
        if self.all_clients:
            self.client_ids = self._search_clients_for_filter()

    def action_stop_clients(self):
        return self._execute_operation("stop")

    def action_restart_clients(self):
        return self._execute_operation("restart")

    def action_delete_clients(self):
        return self._execute_operation("delete")

    def _execute_operation(self, operation):
        self.ensure_one()
        clients = self._get_operation_clients()
        if not clients:
            raise UserError(_("Select at least one SaaS client."))
        if operation == "delete" and not self.confirm_delete:
            raise UserError(_("You must confirm deletion before deleting SaaS clients."))

        clients._check_bulk_restart_access()
        method_name = self._find_operation_method_name(clients, operation)

        success_clients = self.env["saas.client"]
        failed = []
        for client in clients:
            try:
                with self.env.cr.savepoint():
                    if method_name:
                        getattr(client, method_name)()
                    else:
                        client.unlink()
                    success_clients |= client
                    if operation != "delete" and hasattr(client, "message_post"):
                        client.message_post(
                            body=_("Bulk %s requested by %s.")
                            % (operation, self.env.user.display_name)
                        )
            except Exception as error:
                _logger.exception("Bulk %s failed for SaaS client %s", operation, client.display_name)
                failed.append((client.display_name, str(error)))

        operation_labels = {
            "stop": _("stopped"),
            "restart": _("restarted"),
            "delete": _("deleted"),
        }
        message = _("%s SaaS client(s) %s.") % (
            len(success_clients),
            operation_labels[operation],
        )
        if failed:
            message += "\n" + _("%s client(s) failed:") % len(failed)
            message += "\n" + "\n".join("- %s: %s" % item for item in failed)

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("SaaS Operations"),
                "message": message,
                "type": "warning" if failed else "success",
                "sticky": bool(failed),
                "next": {"type": "ir.actions.act_window_close"},
            },
        }

    def _get_operation_clients(self):
        self.ensure_one()
        if self.all_clients:
            return self._search_clients_for_filter()
        return self.client_ids

    def _search_clients_for_filter(self):
        domain = []
        if self.state_filter == "started":
            domain = [("state", "in", ("started", "Started"))]
        elif self.state_filter == "stopped":
            domain = [("state", "in", ("stopped", "Stopped"))]
        return self.env["saas.client"].search(domain)

    def _find_operation_method_name(self, clients, operation):
        if operation == "restart":
            return self._find_restart_method_name(clients)
        if operation == "stop":
            return self._find_stop_method_name(clients)
        if operation == "delete":
            return self._find_delete_method_name(clients)
        raise UserError(_("Unsupported operation."))

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

    def _find_stop_method_name(self, clients):
        candidate_names = (
            "action_stop",
            "button_stop",
            "stop",
            "stop_server",
            "stop_client",
            "stop_saas",
            "stop_instance",
            "action_stop_server",
            "action_stop_client",
            "action_stop_instance",
            "action_stop_container",
            "server_stop",
            "stop_container",
            "stop_odoo",
            "action_stop_odoo",
        )
        for method_name in candidate_names:
            method = getattr(clients[:1], method_name, None)
            if callable(method):
                return method_name

        for method_name in self._find_methods_from_views("Stop"):
            method = getattr(clients[:1], method_name, None)
            if callable(method):
                return method_name

        raise UserError(
            _(
                "No stop method was found on saas.client. "
                "Open the original SaaS Kit form view and check the technical name of the Stop button."
            )
        )

    def _find_delete_method_name(self, clients):
        candidate_names = (
            "action_delete",
            "button_delete",
            "delete",
            "delete_server",
            "delete_client",
            "delete_saas",
            "delete_instance",
            "action_delete_server",
            "action_delete_client",
            "action_delete_instance",
            "remove_instance",
            "drop_instance",
            "unlink_instance",
            "action_remove_instance",
            "action_drop_database",
            "drop_database",
        )
        for method_name in candidate_names:
            method = getattr(clients[:1], method_name, None)
            if callable(method):
                return method_name

        for label in ("Delete", "Remove", "Drop"):
            for method_name in self._find_methods_from_views(label):
                method = getattr(clients[:1], method_name, None)
                if callable(method):
                    return method_name

        return False

    def _find_restart_methods_from_views(self):
        return self._find_methods_from_views("Restart")

    def _find_methods_from_views(self, button_label):
        views = self.env["ir.ui.view"].sudo().search([
            ("model", "=", "saas.client"),
            ("arch_db", "ilike", button_label),
        ])
        method_names = []
        for view in views:
            arch = str(view.arch_db or "")
            for button in re.findall(r"<button\b[^>]*>", arch, flags=re.IGNORECASE):
                pattern = r"\bstring=['\"]%s['\"]" % re.escape(button_label)
                if not re.search(pattern, button, flags=re.IGNORECASE):
                    continue
                match = re.search(r"\bname=['\"]([^'\"]+)['\"]", button)
                if match:
                    method_names.append(match.group(1))
        return method_names

    @api.model
    def _install_or_update_list_button(self):
        View = self.env["ir.ui.view"].sudo()
        ModelData = self.env["ir.model.data"].sudo()
        xmlid = ModelData.search([
            ("module", "=", "saas_bulk_restart"),
            ("name", "=", "view_saas_client_bulk_restart_header"),
        ], limit=1)

        list_view = View.search([
            ("model", "=", "saas.client"),
            ("type", "in", ("list", "tree")),
            ("mode", "=", "primary"),
        ], order="priority, id", limit=1)
        if not list_view:
            list_view = View.search([
                ("model", "=", "saas.client"),
                ("type", "in", ("list", "tree")),
            ], order="priority, id", limit=1)
        if not list_view:
            return

        root_tag = "list" if list_view.type == "list" else "tree"
        values = {
            "name": "saas.client.bulk.operations.header",
            "model": "saas.client",
            "type": list_view.type,
            "mode": "extension",
            "inherit_id": list_view.id,
            "arch_db": """
                <data>
                    <xpath expr="//%s" position="inside">
                        <header>
                            <button
                                name="action_open_saas_operations_wizard"
                                type="object"
                                string="SaaS Operations"
                                class="btn-primary"
                                display="always"
                            />
                        </header>
                    </xpath>
                </data>
            """ % root_tag,
        }
        if xmlid and xmlid.res_id:
            View.browse(xmlid.res_id).write(values)
            return

        inherited_view = View.create(values)
        ModelData.create({
            "module": "saas_bulk_restart",
            "name": "view_saas_client_bulk_restart_header",
            "model": "ir.ui.view",
            "res_id": inherited_view.id,
            "noupdate": True,
        })
