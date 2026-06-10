# -*- coding: utf-8 -*-

import lxml.html

from odoo import models


class IrActionsReport(models.Model):
    _inherit = "ir.actions.report"

    def _pre_render_qweb_pdf(self, report_ref, res_ids=None, data=None):
        if not self.env.context.get("sunapp_force_report_rendering"):
            return super(
                IrActionsReport,
                self.with_context(
                    report_pdf_no_attachment=True,
                    sunapp_force_report_rendering=True,
                ),
            )._pre_render_qweb_pdf(report_ref, res_ids=res_ids, data=data)
        return super()._pre_render_qweb_pdf(report_ref, res_ids=res_ids, data=data)

    def _prepare_html(self, html, report_model=False):
        bodies, res_ids, header, footer, specific_paperformat_args = super()._prepare_html(
            html,
            report_model=report_model,
        )
        return (
            bodies,
            res_ids,
            header,
            self._sunapp_add_report_footer_notice(footer),
            self._sunapp_ensure_footer_margin(specific_paperformat_args),
        )

    def _run_wkhtmltopdf(
        self,
        bodies,
        report_ref=False,
        header=None,
        footer=None,
        landscape=False,
        specific_paperformat_args=None,
        set_viewport_size=False,
    ):
        return super()._run_wkhtmltopdf(
            bodies,
            report_ref=report_ref,
            header=header,
            footer=self._sunapp_add_report_footer_notice(footer),
            landscape=landscape,
            specific_paperformat_args=self._sunapp_ensure_footer_margin(specific_paperformat_args),
            set_viewport_size=set_viewport_size,
        )

    def _sunapp_add_report_footer_notice(self, html):
        if not html:
            return self._sunapp_notice_html()

        root = lxml.html.fromstring(html, parser=lxml.html.HTMLParser(encoding="utf-8"))
        if root.xpath("//*[contains(concat(' ', normalize-space(@class), ' '), ' o_sunapp_report_notice ')]"):
            return html

        notice = lxml.html.fragment_fromstring(self._sunapp_notice_html())
        footer = root.xpath(
            "//*[contains(concat(' ', normalize-space(@class), ' '), ' footer ')]"
        )
        target = footer[-1] if footer else root.find("body")
        if target is None:
            target = root
        target.append(notice)
        return lxml.html.tostring(root, encoding="unicode")

    def _sunapp_notice_html(self):
        return (
            '<div class="o_sunapp_report_notice" '
            'style="clear:both; width:100%; text-align:center; font-size:10px; '
            'line-height:12px; color:#777; margin-top:3px;">'
            'Généré par SunApp</div>'
        )

    def _sunapp_ensure_footer_margin(self, specific_paperformat_args):
        specific_paperformat_args = dict(specific_paperformat_args or {})
        margin_bottom = specific_paperformat_args.get("data-report-margin-bottom")
        try:
            margin_bottom = float(margin_bottom) if margin_bottom is not None else 0.0
        except (TypeError, ValueError):
            margin_bottom = 0.0
        if margin_bottom < 15.0:
            specific_paperformat_args["data-report-margin-bottom"] = "15"
        return specific_paperformat_args
