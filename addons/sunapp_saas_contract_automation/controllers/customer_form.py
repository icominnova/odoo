import re

from odoo import http
from odoo.http import content_disposition, request

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
        saas_status = order.sunapp_saas_public_status()
        completed_steps = sum(
            (
                1,
                int(order.state in ("sale", "done")),
                int(saas_status["contract_found"]),
                int(saas_status["contract_confirmed"]),
                int(saas_status["instance_ready"]),
                int(saas_status["ready"]),
            )
        )
        return request.make_json_response(
            {
                "status": "ready" if saas_status["ready"] else "processing",
                "order_name": order.name,
                "customer_existing": not request.session.get(
                    "sunapp_customer_created", False
                ),
                "steps": {
                    "customer": True,
                    "order": order.state in ("sale", "done"),
                    "contract": saas_status["contract_found"],
                    "confirmation": saas_status["contract_confirmed"],
                    "instance": saas_status["instance_ready"],
                    "credentials": saas_status["ready"],
                },
                "progress": round(completed_steps * 100 / 6),
                "error": saas_status["error"],
                "instance_url": saas_status["instance_url"],
                "download_url": (
                    "/formulaire-client/identifiants" if saas_status["ready"] else False
                ),
            }
        )

    @http.route(
        "/formulaire-client/identifiants",
        type="http",
        auth="public",
        website=True,
        methods=["GET"],
        csrf=False,
        sitemap=False,
    )
    def customer_credentials_download(self, **kwargs):
        order = request.env["sale.order"].sudo().browse(
            request.session.get("sunapp_sale_order_id")
        ).exists()
        if not order:
            return request.not_found()
        credentials = order.sunapp_saas_credentials()
        if not credentials["ready"]:
            return request.not_found()
        password = credentials["password"] or "Transmis séparément par e-mail"
        content = (
            "IDENTIFIANTS SUNAPP\n"
            "===================\n\n"
            f"Espace : {credentials['url']}\n"
            f"Identifiant : {credentials['login']}\n"
            f"Mot de passe temporaire : {password}\n\n"
            "Modifiez votre mot de passe lors de votre première connexion.\n"
        )
        filename = f"identifiants-sunapp-{order.name}.txt"
        return request.make_response(
            content,
            headers=[
                ("Content-Type", "text/plain; charset=utf-8"),
                ("Content-Disposition", content_disposition(filename)),
                ("Cache-Control", "no-store, private"),
                ("X-Content-Type-Options", "nosniff"),
            ],
        )

    @http.route()
    def customer_form_submit(self, **post):
        return super().customer_form_submit(**post)
