import re

from odoo import Command, fields, http
from odoo.http import request
from odoo.tools import email_normalize


class SunAppCustomerForm(http.Controller):
    @staticmethod
    def _clean(value, limit=255):
        return (value or "").strip()[:limit]

    @staticmethod
    def _phone_key(value):
        return re.sub(r"\D", "", value or "")

    def _extra_form_values(self, post):
        """Extension hook for optional modules adding fields to the form."""
        return {}

    def _extra_partner_values(self, values):
        return {}

    def _extra_form_errors(self, values):
        return {}

    def _extra_sale_order_values(self, values):
        return {}

    def _after_sale_order_confirm(self, sale_order, values):
        return None

    def _render_form(self, values=None, errors=None):
        website = request.website
        return request.render(
            "sunapp_customer_form.customer_form_page",
            {
                "values": values or {},
                "errors": errors or {},
                "countries": request.env["res.country"].sudo().search([], order="name"),
                "default_country_id": website.company_id.country_id.id,
            },
        )

    @http.route(
        "/formulaire-client",
        type="http",
        auth="public",
        website=True,
        methods=["GET"],
        sitemap=True,
    )
    def customer_form(self, **kwargs):
        return self._render_form()

    @http.route(
        "/formulaire-client/envoyer",
        type="http",
        auth="public",
        website=True,
        methods=["POST"],
        csrf=True,
        sitemap=False,
    )
    def customer_form_submit(self, **post):
        values = {
            "full_name": self._clean(post.get("full_name")),
            "company_name": self._clean(post.get("company_name")),
            "email": self._clean(post.get("email")).lower(),
            "phone": self._clean(post.get("phone"), limit=64),
            "street": self._clean(post.get("street")),
            "city": self._clean(post.get("city")),
            "country_id": self._clean(post.get("country_id"), limit=16),
            "vat": self._clean(post.get("vat"), limit=64),
            "note": self._clean(post.get("note"), limit=2000),
        }
        values.update(self._extra_form_values(post))

        # Honeypot: silently accept automated submissions without creating data.
        if self._clean(post.get("website_url")):
            return request.redirect("/formulaire-client/merci")

        errors = {}
        for field_name in ("full_name", "company_name", "email", "phone"):
            if not values[field_name]:
                errors[field_name] = "Ce champ est obligatoire."
        errors.update(self._extra_form_errors(values))

        normalized_email = email_normalize(values["email"], strict=False)
        if values["email"] and not normalized_email:
            errors["email"] = "Saisissez une adresse email valide."

        phone_key = self._phone_key(values["phone"])
        if values["phone"] and len(phone_key) < 8:
            errors["phone"] = "Saisissez un numero de telephone valide."

        country = request.env["res.country"].sudo().browse()
        if values["country_id"].isdigit():
            country = request.env["res.country"].sudo().browse(int(values["country_id"])).exists()

        if errors:
            return self._render_form(values=values, errors=errors)

        company = request.website.company_id
        Product = request.env["product.product"].sudo()
        product_domain = [
            ("sale_ok", "=", True),
            "|",
            ("company_id", "=", False),
            ("company_id", "=", company.id),
        ]
        product = Product.search(
            [
                ("name", "=ilike", "Abonnement Standart"),
                *product_domain,
            ],
            limit=1,
        )
        if not product:
            errors["_global"] = (
                "Le produit Abonnement Standart est indisponible. "
                "Contactez un administrateur."
            )
            return self._render_form(values=values, errors=errors)

        Partner = request.env["res.partner"].sudo().with_context(active_test=False)
        partner = Partner.search(
            [("email_normalized", "=", normalized_email)],
            limit=1,
        )
        if not partner and values["phone"]:
            candidates = Partner.search(
                [("phone", "!=", False)],
                limit=500,
            )
            partner = candidates.filtered(
                lambda item: phone_key == self._phone_key(item.phone)
            )[:1]

        company_partner = partner.parent_id if partner and partner.parent_id else partner
        created = False
        if not company_partner:
            partner_values = {
                "name": values["company_name"],
                "company_type": "company",
                "is_company": True,
                "email": normalized_email,
                "phone": values["phone"],
                "street": values["street"],
                "city": values["city"],
                "country_id": country.id or False,
                "vat": values["vat"] or False,
                "comment": values["note"] or False,
                "customer_rank": 1,
            }
            partner_values.update(self._extra_partner_values(values))
            company_partner = Partner.create(partner_values)
            created = True
        else:
            extra_partner_values = self._extra_partner_values(values)
            if extra_partner_values:
                company_partner.write(extra_partner_values)

        contact = Partner.search(
            [
                ("parent_id", "=", company_partner.id),
                ("email_normalized", "=", normalized_email),
            ],
            limit=1,
        )
        if not contact and values["full_name"] != company_partner.name:
            contact = Partner.create(
                {
                    "name": values["full_name"],
                    "parent_id": company_partner.id,
                    "type": "contact",
                    "email": normalized_email,
                    "phone": values["phone"],
                }
            )

        SaleOrder = request.env["sale.order"].sudo()
        sale_order = SaleOrder.browse(
            request.session.get("sunapp_sale_order_id")
        ).exists()
        if (
            not sale_order
            or sale_order.partner_id != company_partner
            or sale_order.state not in ("draft", "sent", "sale", "done")
        ):
            recent_limit = fields.Datetime.subtract(fields.Datetime.now(), minutes=10)
            sale_order = SaleOrder.search(
                [
                    ("partner_id", "=", company_partner.id),
                    ("state", "in", ["draft", "sent", "sale", "done"]),
                    ("origin", "=", "Formulaire client SunApp"),
                    ("create_date", ">=", recent_limit),
                    ("order_line.product_id", "=", product.id),
                ],
                order="id desc",
                limit=1,
            )

        if not sale_order:
            salesperson = company_partner.user_id
            if not salesperson:
                salesperson = request.env["res.users"].sudo().search(
                    [
                        ("active", "=", True),
                        ("share", "=", False),
                        ("company_ids", "in", company.id),
                    ],
                    order="id",
                    limit=1,
                )
            order_values = {
                "partner_id": company_partner.id,
                "company_id": company.id,
                "origin": "Formulaire client SunApp",
                "order_line": [
                    Command.create(
                        {
                            "product_id": product.id,
                            "product_uom_qty": 12.0,
                        }
                    )
                ],
            }
            order_values.update(self._extra_sale_order_values(values))
            if salesperson:
                order_values["user_id"] = salesperson.id
            sale_order = SaleOrder.create(order_values)

        if sale_order.state in ("draft", "sent"):
            sale_order.action_confirm()
        self._after_sale_order_confirm(sale_order, values)

        request.session["sunapp_customer_partner_id"] = company_partner.id
        request.session["sunapp_customer_contact_id"] = contact.id if contact else False
        request.session["sunapp_customer_created"] = created
        request.session["sunapp_sale_order_id"] = sale_order.id
        request.session["sunapp_sale_order_name"] = sale_order.name
        return request.redirect("/formulaire-client/merci")

    @http.route(
        "/formulaire-client/merci",
        type="http",
        auth="public",
        website=True,
        methods=["GET"],
        sitemap=False,
    )
    def customer_form_success(self, **kwargs):
        return request.render(
            "sunapp_customer_form.customer_form_success",
            {
                "sale_order_name": request.session.get("sunapp_sale_order_name"),
            },
        )
