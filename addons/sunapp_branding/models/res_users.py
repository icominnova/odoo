# -*- coding: utf-8 -*-

from markupsafe import Markup

from odoo import _, models


class ResUsers(models.Model):
    _inherit = "res.users"

    def _init_odoobot(self):
        self.ensure_one()
        bot_partner = self.env.ref("base.partner_root").sudo()
        bot_partner.name = "SunAppBot"
        channel = self.env["discuss.channel"]._get_or_create_chat([bot_partner.id, self.partner_id.id])
        message = Markup("%s<br/>%s<br/><b>%s</b> <span class=\"o_odoobot_command\">:)</span>") % (
            _("Hello,"),
            _("SunApp's chat helps employees collaborate efficiently. I'm here to help you discover its features."),
            _("Try to send me an emoji"),
        )
        channel.sudo().message_post(
            author_id=bot_partner.id,
            body=message,
            message_type="comment",
            silent=True,
            subtype_xmlid="mail.mt_comment",
        )
        self.sudo().odoobot_state = "onboarding_emoji"
        return channel
