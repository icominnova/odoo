from odoo import fields, models


class SaasClientHealthLog(models.Model):
    _name = "saas.client.health.log"
    _description = "SaaS Client Health History"
    _order = "event_date desc, id desc"

    client_id = fields.Many2one(
        "saas.client",
        string="SaaS Client",
        required=True,
        index=True,
        ondelete="cascade",
    )
    event_date = fields.Datetime(
        string="Date",
        default=fields.Datetime.now,
        required=True,
        index=True,
    )
    event_type = fields.Selection(
        [
            ("health_online", "Health Online"),
            ("health_offline", "Health Offline"),
            ("health_unknown", "Health Unknown"),
            ("manual_stop", "Manual Stop"),
            ("manual_restart", "Manual Restart"),
            ("manual_delete", "Manual Delete"),
            ("auto_restart", "Auto Restart"),
            ("auto_restart_blocked", "Auto Restart Blocked"),
            ("auto_restart_enabled", "Auto Restart Enabled"),
            ("auto_restart_disabled", "Auto Restart Disabled"),
            ("error", "Error"),
        ],
        string="Event",
        required=True,
        index=True,
    )
    health_state = fields.Selection(
        [
            ("unknown", "Unknown"),
            ("online", "Online"),
            ("offline", "Offline"),
            ("restarting", "Restarting"),
            ("blocked", "Blocked"),
        ],
        string="Real Status",
        index=True,
    )
    http_status = fields.Integer(string="HTTP Status")
    failure_count = fields.Integer(string="Failures")
    auto_restart_attempt_count = fields.Integer(string="Auto Restart Attempts")
    url = fields.Char(string="Checked URL")
    message = fields.Text(string="Message")
    user_id = fields.Many2one(
        "res.users",
        string="User",
        default=lambda self: self.env.user,
        readonly=True,
    )
