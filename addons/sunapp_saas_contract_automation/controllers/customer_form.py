import re

from odoo import http
from odoo.http import request

from odoo.addons.sunapp_customer_form.controllers.customer_form import (
    SunAppCustomerForm,
)


DOMAIN_RE = re.compile(
    r"^(?=.{3,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)


class SunAppSaaSCustomerForm(SunAppCustomerForm):
    @staticmethod
    def _normalize_domain(value):
        domain = (value or "").strip().lower()
        domain = re.sub(r"^https?://", "", domain)
        return domain.split("/", 1)[0].strip(".")[:253]

    def _extra_form_values(self, post):
        values = super()._extra_form_values(post)
        values["saas_domain_name"] = self._normalize_domain(
            post.get("saas_domain_name")
        )
        return values

    def _extra_form_errors(self, values):
        errors = super()._extra_form_errors(values)
        domain = values.get("saas_domain_name")
        if not domain:
            errors["saas_domain_name"] = "Le nom de domaine est obligatoire."
        elif not DOMAIN_RE.fullmatch(domain):
            errors["saas_domain_name"] = "Saisissez un nom de domaine valide."
        else:
            existing_partner = request.env["res.partner"].sudo().search(
                [("sunapp_saas_domain_name", "=", domain)], limit=1
            )
            if existing_partner and existing_partner.email_normalized != values.get("email"):
                errors["saas_domain_name"] = "Ce nom de domaine est déjà utilisé."
        return errors

    def _extra_partner_values(self, values):
        partner_values = super()._extra_partner_values(values)
        partner_values["sunapp_saas_domain_name"] = values["saas_domain_name"]
        return partner_values

    def _extra_sale_order_values(self, values):
        order_values = super()._extra_sale_order_values(values)
        order_values.update(
            {
                "sunapp_saas_domain_name": values["saas_domain_name"],
                "sunapp_saas_automation_state": "pending",
            }
        )
        return order_values

    def _after_sale_order_confirm(self, sale_order, values):
        super()._after_sale_order_confirm(sale_order, values)
        sale_order.write(
            {
                "sunapp_saas_domain_name": values["saas_domain_name"],
                "sunapp_saas_automation_state": "pending",
                "sunapp_saas_automation_error": False,
            }
        )

    @http.route(
        "/formulaire-client/statut",
        type="http",
        auth="public",
        website=True,
        methods=["GET"],
        csrf=False,
        sitemap=False,
    )
    def customer_form_status(self, **kwargs):
        order = request.env["sale.order"].sudo().browse(
            request.session.get("sunapp_sale_order_id")
        ).exists()
        if not order:
            return request.make_json_response({"status": "missing"}, status=404)
        return request.make_json_response(
            {
                "status": (
                    "ready"
                    if order.sunapp_saas_automation_state == "done"
                    else "processing"
                ),
                "order_name": order.name,
            }
        )

    @http.route()
    def customer_form_submit(self, **post):
        return super().customer_form_submit(**post)
