# -*- coding: utf-8 -*-

from markupsafe import Markup

from odoo import models


SUNAPP_BOT_REPLACEMENTS = (
    ("OdooBot", "SunAppBot"),
    ("Odoo's chat", "SunApp's chat"),
    ("Odoo&#39;s chat", "SunApp&#39;s chat"),
    ("Odoo&apos;s chat", "SunApp&apos;s chat"),
    ("Le Chat d'Odoo", "Le Chat de SunApp"),
    ("Enjoy exploring Odoo!", "Enjoy exploring SunApp!"),
)


def sunapp_replace_bot_branding(value):
    text = str(value or "")
    for source, target in SUNAPP_BOT_REPLACEMENTS:
        text = text.replace(source, target)
    return text


class MailBot(models.AbstractModel):
    _inherit = "mail.bot"

    def _get_answer(self, channel, body, values, command=False):
        answer = super()._get_answer(channel, body, values, command=command)
        return self._sunapp_brand_bot_answer(answer)

    def _sunapp_brand_bot_answer(self, answer):
        if isinstance(answer, list):
            return [self._sunapp_brand_bot_answer(item) for item in answer]
        if isinstance(answer, Markup):
            return Markup(sunapp_replace_bot_branding(answer))
        if isinstance(answer, str):
            return sunapp_replace_bot_branding(answer)
        return answer
