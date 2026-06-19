import logging
import re
from urllib.parse import urlparse

from odoo import api, fields, models
from odoo.tools import html2plaintext


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
    "create_saas_client",
    "action_create_and_confirm_client",
    "create_and_confirm_client",
    "action_create_confirm_client",
    "create_confirm_client",
    "action_confirm_contract",
    "confirm_contract",
    "action_confirm",
)
CONFIRMED_STATES = {"confirm", "confirmed", "active", "running"}
PASSWORD_FIELDS = (
    "temporary_password",
    "temp_password",
    "admin_password",
    "password",
)
URL_FIELDS = ("url", "instance_url", "client_url", "access_url", "base_url")


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
        domain_value = self.sunapp_saas_domain_name
        if (
            "use_separate_domain" in contract._fields
            and not contract.use_separate_domain
            and "saas_domain_url" in contract._fields
            and contract.saas_domain_url
        ):
            base_domain = contract.saas_domain_url.strip().lower().strip(".")
            suffix = f".{base_domain}"
            if domain_value.lower().endswith(suffix):
                domain_value = domain_value[: -len(suffix)].strip(".")
        for field_name in DOMAIN_FIELDS:
            field = contract._fields.get(field_name)
            if field and field.type in ("char", "text"):
                contract.write({field_name: domain_value})
                return field_name
        for field_name, field in contract._fields.items():
            if "domain" in field_name.lower() and field.type in ("char", "text"):
                contract.write({field_name: domain_value})
                return field_name
        return False

    def _sunapp_prepare_contract(self, contract):
        self.ensure_one()
        values = {}
        if "pricelist_id" in contract._fields and not contract.pricelist_id:
            values["pricelist_id"] = self.pricelist_id.id
        if "company_id" in contract._fields and not contract.company_id:
            values["company_id"] = self.company_id.id
        if "partner_id" in contract._fields and not contract.partner_id:
            values["partner_id"] = self.partner_id.commercial_partner_id.id
        if "invoice_product_id" in contract._fields and not contract.invoice_product_id:
            product = self.order_line.filtered(lambda line: not line.display_type)[:1].product_id
            if product:
                values["invoice_product_id"] = product.id
        if "journal_id" in contract._fields and not contract.journal_id:
            journal = self.env["account.journal"].sudo().search(
                [
                    ("type", "=", "sale"),
                    ("company_id", "=", self.company_id.id),
                ],
                order="sequence, id",
                limit=1,
            )
            if journal:
                values["journal_id"] = journal.id
        if values:
            contract.write(values)
        return values

    def _sunapp_confirm_contract(self, contract):
        state = contract["state"] if "state" in contract._fields else False
        if state in CONFIRMED_STATES:
            actions = []
            if "user_data_error" in contract._fields and contract.user_data_error:
                raise ValueError(
                    "La configuration des données utilisateur a échoué. Une nouvelle tentative sera effectuée."
                )
            if "invitation_mail_error" in contract._fields and contract.invitation_mail_error:
                raise ValueError(
                    "L'envoi des identifiants a échoué. Une nouvelle tentative sera effectuée."
                )
            if (
                "user_data_updated" in contract._fields
                and not contract.user_data_updated
                and not contract.user_data_error
                and callable(getattr(contract, "update_user_data", None))
            ):
                contract.update_user_data()
                actions.append("update_user_data")
            if (
                "user_data_updated" in contract._fields
                and contract.user_data_updated
                and "invitation_mail_sent" in contract._fields
                and not contract.invitation_mail_sent
                and callable(getattr(contract, "send_invitation_email", None))
            ):
                contract.send_invitation_email()
                actions.append("send_invitation_email")
            return ",".join(actions) or "already_confirmed"

        if contract._name == "saas.contract" and "saas_client" in contract._fields:
            if not contract.saas_client:
                contract.create_saas_client()
                return "create_saas_client"
            if state == "draft" and callable(getattr(contract, "mark_confirmed", None)):
                contract.mark_confirmed()
                return "mark_confirmed"
            if state == "open" and callable(getattr(contract, "send_credential_email", None)):
                contract.send_credential_email()
                return "send_credential_email"
        for method_name in CONFIRM_METHODS:
            method = getattr(contract, method_name, None)
            if callable(method):
                method()
                return method_name
        view_arch = contract.get_view(view_type="form").get("arch")
        if view_arch is not None:
            for button in view_arch.xpath("//button[@type='object'][@name]"):
                label = (button.get("string") or "").lower()
                if "confirm" not in label or not (
                    "client" in label or "contract" in label
                ):
                    continue
                method_name = button.get("name")
                contract_with_context = contract.with_context(
                    active_id=contract.id,
                    active_ids=contract.ids,
                    active_model=contract._name,
                )
                method = getattr(contract_with_context, method_name, None)
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

    def _sunapp_contract_workflow_complete(self, contract, public_status):
        complete = public_status["ready"]
        if contract and "user_data_updated" in contract._fields:
            complete = complete and contract.user_data_updated
        if contract and "invitation_mail_sent" in contract._fields:
            complete = complete and contract.invitation_mail_sent
        return bool(complete)

    def _sunapp_contract_client(self, contract):
        if contract and "saas_client" in contract._fields:
            return contract.saas_client.sudo()
        return self.env["res.partner"].browse()

    def _sunapp_instance_url(self, contract, client):
        for record in (client, contract):
            if not record:
                continue
            for field_name in URL_FIELDS:
                if field_name in record._fields and record[field_name]:
                    url = str(record[field_name]).strip()
                    if not url.startswith(("http://", "https://")):
                        url = f"https://{url}"
                    if urlparse(url).scheme in ("http", "https"):
                        return url
        if self.sunapp_saas_domain_name:
            return f"https://{self.sunapp_saas_domain_name}"
        return False

    def _sunapp_temporary_password(self, contract, client):
        for record in (client, contract):
            if not record:
                continue
            for field_name in PASSWORD_FIELDS:
                if field_name in record._fields and record[field_name]:
                    return str(record[field_name])
        password_pattern = re.compile(
            r"temporary\s+password\s+is\s*:\s*(\S+)", re.IGNORECASE
        )
        for record in (client, contract):
            if not record or "message_ids" not in record._fields:
                continue
            for message in record.message_ids.sorted("date", reverse=True):
                match = password_pattern.search(html2plaintext(message.body or ""))
                if match:
                    return match.group(1).strip()
        return False

    def sunapp_saas_public_status(self):
        self.ensure_one()
        contract = self._sunapp_find_linked_contract()
        client = self._sunapp_contract_client(contract)
        contract_state = (
            contract.state if contract and "state" in contract._fields else False
        )
        client_state = client.state if client and "state" in client._fields else False
        instance_url = self._sunapp_instance_url(contract, client)
        instance_ready = bool(
            contract
            and contract_state in CONFIRMED_STATES
            and client
            and instance_url
            and client_state not in ("draft", "inactive", "cancel")
        )
        ready = instance_ready
        if contract and "user_data_updated" in contract._fields:
            ready = ready and contract.user_data_updated
        if contract and "invitation_mail_sent" in contract._fields:
            ready = ready and contract.invitation_mail_sent
        return {
            "ready": bool(ready),
            "instance_ready": instance_ready,
            "contract_found": bool(contract),
            "contract_confirmed": contract_state in CONFIRMED_STATES,
            "client_created": bool(client),
            "instance_url": instance_url if instance_ready else False,
            "error": self.sunapp_saas_automation_error or False,
        }

    def sunapp_saas_credentials(self):
        self.ensure_one()
        contract = self._sunapp_find_linked_contract()
        client = self._sunapp_contract_client(contract)
        status = self.sunapp_saas_public_status()
        return {
            "ready": status["ready"],
            "url": status["instance_url"],
            "login": self.partner_id.email or "",
            "password": self._sunapp_temporary_password(contract, client) or "",
        }

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
                    order._sunapp_prepare_contract(contract)
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
                public_status = order.sunapp_saas_public_status()
                workflow_complete = order._sunapp_contract_workflow_complete(
                    contract, public_status
                )
                order.write(
                    {
                        "sunapp_saas_automation_state": (
                            "done" if workflow_complete else "pending"
                        ),
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
