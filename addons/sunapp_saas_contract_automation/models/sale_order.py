import logging

from odoo import api, fields, models


_logger = logging.getLogger(__name__)


DOMAIN_FIELDS = (
    "domain_name",
    "sub_domain_name",
    "subdomain_name",
    "sub_domain",
    "subdomain",
    "client_domain",
    "client_domain_name",
    "saas_domain_name",
)
CONFIRM_METHODS = (
    "action_create_and_confirm_client",
    "create_and_confirm_client",
    "action_create_confirm_client",
    "create_confirm_client",
    "action_confirm_contract",
    "confirm_contract",
    "action_confirm",
)
CONFIRMED_STATES = {"confirm", "confirmed", "active", "running"}


class SaleOrder(models.Model):
    _inherit = "sale.order"

    sunapp_saas_domain_name = fields.Char(
        string="Nom de domaine SaaS",
        copy=False,
        index=True,
    )
    sunapp_saas_automation_state = fields.Selection(
        [
            ("pending", "En attente"),
            ("done", "Terminé"),
            ("error", "Erreur"),
        ],
        string="Automatisation SaaS",
        copy=False,
        default=False,
        readonly=True,
    )
    sunapp_saas_automation_error = fields.Text(
        string="Erreur d'automatisation SaaS",
        copy=False,
        readonly=True,
    )
    sunapp_saas_contract_model = fields.Char(copy=False, readonly=True)
    sunapp_saas_contract_id = fields.Integer(copy=False, readonly=True)

    def _sunapp_contract_models(self):
        model_names = []
        for name in self.env.registry.models:
            if "contract" not in name.lower():
                continue
            field_names = self.env[name]._fields
            is_saas_contract = "saas" in name.lower() or any(
                marker in field_names
                for marker in ("saas_server_id", "db_template_id", "domain_name", "sub_domain_name")
            )
            if is_saas_contract:
                model_names.append(name)
        return sorted(model_names, key=lambda name: (name != "saas.contract", name))

    def _sunapp_find_linked_contract(self):
        self.ensure_one()
        if self.sunapp_saas_contract_model and self.sunapp_saas_contract_id:
            model_name = self.sunapp_saas_contract_model
            if model_name in self.env:
                contract = self.env[model_name].sudo().browse(
                    self.sunapp_saas_contract_id
                ).exists()
                if contract:
                    return contract

        for field in self._fields.values():
            if (
                field.type in ("many2one", "one2many", "many2many")
                and field.comodel_name
                and "saas" in field.comodel_name.lower()
                and "contract" in field.comodel_name.lower()
            ):
                contract = self[field.name][:1]
                if contract:
                    return contract.sudo()

        relation_fields = ("sale_order_id", "order_id", "so_id")
        partner_fields = ("partner_id", "customer_id", "client_partner_id")
        recent_limit = fields.Datetime.subtract(self.create_date, minutes=5)
        for model_name in self._sunapp_contract_models():
            Contract = self.env[model_name].sudo()
            for field_name in relation_fields:
                field = Contract._fields.get(field_name)
                if field and field.type == "many2one" and field.comodel_name == "sale.order":
                    contract = Contract.search([(field_name, "=", self.id)], limit=1)
                    if contract:
                        return contract
            for field_name in partner_fields:
                field = Contract._fields.get(field_name)
                if field and field.type == "many2one" and field.comodel_name == "res.partner":
                    contract = Contract.search(
                        [
                            (field_name, "=", self.partner_id.commercial_partner_id.id),
                            ("create_date", ">=", recent_limit),
                        ],
                        order="id desc",
                        limit=1,
                    )
                    if contract:
                        return contract
        return self.env["sale.order"].browse()

    def _sunapp_set_contract_domain(self, contract):
        self.ensure_one()
        for field_name in DOMAIN_FIELDS:
            field = contract._fields.get(field_name)
            if field and field.type in ("char", "text"):
                contract.write({field_name: self.sunapp_saas_domain_name})
                return field_name
        for field_name, field in contract._fields.items():
            if "domain" in field_name.lower() and field.type in ("char", "text"):
                contract.write({field_name: self.sunapp_saas_domain_name})
                return field_name
        return False

    def _sunapp_confirm_contract(self, contract):
        state = contract["state"] if "state" in contract._fields else False
        if state in CONFIRMED_STATES:
            return "already_confirmed"
        for method_name in CONFIRM_METHODS:
            method = getattr(contract, method_name, None)
            if callable(method):
                method()
                return method_name
        for method_name in dir(type(contract)):
            lowered_name = method_name.lower()
            if "confirm" not in lowered_name or not (
                "client" in lowered_name or "contract" in lowered_name
            ):
                continue
            method = getattr(contract, method_name, None)
            if callable(method):
                method()
                return method_name
        return False

    def sunapp_process_saas_contract(self):
        for order in self.sudo():
            if not order.sunapp_saas_domain_name or order.state not in ("sale", "done"):
                continue
            try:
                with self.env.cr.savepoint():
                    contract = order._sunapp_find_linked_contract()
                    if not contract:
                        order.write(
                            {
                                "sunapp_saas_automation_state": "pending",
                                "sunapp_saas_automation_error": (
                                    "Le contrat SaaS lié n'est pas encore disponible."
                                ),
                            }
                        )
                        continue
                    domain_field = order._sunapp_set_contract_domain(contract)
                    if not domain_field:
                        raise ValueError(
                            "Aucun champ de domaine compatible trouvé sur "
                            f"{contract._name}."
                        )
                    method_name = order._sunapp_confirm_contract(contract)
                    if not method_name:
                        raise ValueError(
                            "Aucune méthode de confirmation compatible trouvée sur "
                            f"{contract._name}."
                        )
                order.write(
                    {
                        "sunapp_saas_automation_state": "done",
                        "sunapp_saas_automation_error": False,
                        "sunapp_saas_contract_model": contract._name,
                        "sunapp_saas_contract_id": contract.id,
                    }
                )
                _logger.info(
                    "Contrat SaaS %s,%s traité depuis %s via %s (domaine: %s)",
                    contract._name,
                    contract.id,
                    order.name,
                    method_name,
                    domain_field,
                )
            except Exception as error:  # Keep the public form transaction usable.
                _logger.exception("Échec de l'automatisation SaaS pour %s", order.name)
                order.write(
                    {
                        "sunapp_saas_automation_state": "error",
                        "sunapp_saas_automation_error": str(error),
                    }
                )
        return True

    @api.model
    def _cron_sunapp_process_saas_contracts(self):
        orders = self.sudo().search(
            [
                ("sunapp_saas_domain_name", "!=", False),
                ("sunapp_saas_automation_state", "in", ["pending", "error"]),
                ("state", "in", ["sale", "done"]),
            ],
            order="id",
            limit=100,
        )
        orders.sunapp_process_saas_contract()
