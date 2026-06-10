# -*- coding: utf-8 -*-

from odoo import api, models

from .mail_bot import sunapp_replace_bot_branding


SUNAPP_BOT_NAME = "SunAppBot"


class ResPartner(models.Model):
    _inherit = "res.partner"

    @api.model
    def _sunapp_apply_bot_branding(self):
        self.env["ir.ui.view"].sudo().search([
            ("key", "like", "sunapp_branding.external_layout_%_sunapp_notice"),
        ]).write({"active": False})

        socodif_view = self.env.ref(
            "sunapp_branding.socodif_external_layout_sunapp_notice",
            raise_if_not_found=False,
        )
        if socodif_view:
            socodif_view.sudo().write({"active": False})

        bot_partner = self.env.ref("base.partner_root", raise_if_not_found=False)
        if not bot_partner:
            return

        bot_partner.sudo().write({"name": SUNAPP_BOT_NAME})

        bot_user = self.env.ref("base.user_root", raise_if_not_found=False)
        if bot_user:
            bot_user.sudo().write({"signature": f"<div>{SUNAPP_BOT_NAME}</div>"})

        self.env["discuss.channel"].sudo().search([
            ("channel_type", "=", "chat"),
            ("name", "ilike", "OdooBot"),
        ]).write({"name": SUNAPP_BOT_NAME})

        messages = self.env["mail.message"].sudo().search([
            ("author_id", "=", bot_partner.id),
            ("body", "ilike", "Odoo"),
        ])
        for message in messages:
            message.body = sunapp_replace_bot_branding(message.body)
