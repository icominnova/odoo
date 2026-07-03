import logging

import requests

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)


class SaasClient(models.Model):
    _inherit = "saas.client"

    auto_restart_enabled = fields.Boolean(
        string="Auto Restart",
        help="Allow the monitor to restart this client when its URL is unreachable.",
    )
    auto_restart_intentional_stop = fields.Boolean(
        string="Voluntarily Stopped",
        help="Do not auto-restart this client because it was intentionally stopped.",
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
        default="unknown",
        copy=False,
    )
    last_health_check = fields.Datetime(
        string="Last Health Check",
        copy=False,
    )
    health_message = fields.Char(
        string="Health Message",
        copy=False,
    )
    consecutive_failure_count = fields.Integer(
        string="Failures",
        copy=False,
    )
    last_auto_restart = fields.Datetime(
        string="Last Auto Restart",
        copy=False,
    )
    auto_restart_attempt_count = fields.Integer(
        string="Auto Restart Attempts",
        copy=False,
    )
    health_log_ids = fields.One2many(
        "saas.client.health.log",
        "client_id",
        string="Health History",
        readonly=True,
    )

    def action_open_bulk_restart_wizard(self):
        return self.action_open_saas_operations_wizard()

    def action_open_saas_operations_wizard(self):
        self._check_bulk_restart_access()
        return {
            "type": "ir.actions.act_window",
            "name": _("SaaS Client Operations"),
            "res_model": "saas.bulk.restart.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                **self.env.context,
                "default_client_ids": [(6, 0, self.ids)],
            },
        }

    def _check_bulk_restart_access(self):
        if hasattr(self, "check_access"):
            self.check_access("write")
            return
        self.check_access_rights("write")
        self.check_access_rule("write")

    def action_health_check_now(self):
        for client in self:
            client._check_client_health()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Health Check"),
                "message": _("Health check completed."),
                "type": "success",
            },
        }

    @classmethod
    def _bulk_restart_safe_int(cls, value, default):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @api.model
    def _cron_auto_restart_unreachable_clients(self, limit=50):
        clients = self.search([
            ("auto_restart_enabled", "=", True),
            ("auto_restart_intentional_stop", "=", False),
        ], limit=limit)
        for client in clients:
            try:
                client._health_check_and_auto_restart()
            except Exception:
                _logger.exception("Auto restart monitor failed for SaaS client %s", client.display_name)

    def _health_check_and_auto_restart(self):
        self.ensure_one()
        config = self.env["ir.config_parameter"].sudo()
        failure_threshold = self._bulk_restart_safe_int(
            config.get_param("saas_bulk_restart.failure_threshold"), 2
        )
        cooldown_minutes = self._bulk_restart_safe_int(
            config.get_param("saas_bulk_restart.cooldown_minutes"), 15
        )
        max_attempts = self._bulk_restart_safe_int(
            config.get_param("saas_bulk_restart.max_attempts"), 3
        )

        is_online = self._check_client_health()
        if is_online:
            self.write({
                "auto_restart_attempt_count": 0,
                "auto_restart_intentional_stop": False,
            })
            return

        if self.auto_restart_intentional_stop:
            return
        if self.consecutive_failure_count < failure_threshold:
            return
        if self.auto_restart_attempt_count >= max_attempts:
            self.write({
                "health_state": "blocked",
                "health_message": _("Auto restart blocked after too many failed attempts."),
            })
            self._log_health_event(
                "auto_restart_blocked",
                message=_("Auto restart blocked after %s failed attempt(s).") % max_attempts,
            )
            return
        if self.last_auto_restart:
            elapsed = fields.Datetime.now() - self.last_auto_restart
            if elapsed.total_seconds() < cooldown_minutes * 60:
                return

        self._auto_restart_client()

    def _check_client_health(self):
        self.ensure_one()
        url = self._get_health_url()
        previous_health_state = self.health_state
        previous_failure_count = self.consecutive_failure_count
        if not url:
            self.write({
                "health_state": "unknown",
                "last_health_check": fields.Datetime.now(),
                "health_message": _("No URL configured."),
            })
            if previous_health_state != "unknown":
                self._log_health_event(
                    "health_unknown",
                    health_state="unknown",
                    message=_("No URL configured."),
                )
            return False

        try:
            response = requests.get(url, timeout=10, allow_redirects=True)
            if response.status_code < 500:
                self.write({
                    "health_state": "online",
                    "last_health_check": fields.Datetime.now(),
                    "health_message": _("HTTP %s") % response.status_code,
                    "consecutive_failure_count": 0,
                })
                if previous_health_state != "online" or previous_failure_count:
                    self._log_health_event(
                        "health_online",
                        health_state="online",
                        http_status=response.status_code,
                        url=url,
                        message=_("Client reachable. HTTP %s") % response.status_code,
                    )
                return True
            message = _("HTTP %s") % response.status_code
            http_status = response.status_code
        except requests.RequestException as error:
            message = str(error)[:250]
            http_status = 0

        self.write({
            "health_state": "offline",
            "last_health_check": fields.Datetime.now(),
            "health_message": message,
            "consecutive_failure_count": self.consecutive_failure_count + 1,
        })
        self._log_health_event(
            "health_offline",
            health_state="offline",
            http_status=http_status,
            url=url,
            message=message,
        )
        return False

    def _get_health_url(self):
        self.ensure_one()
        base_url = getattr(self, "url", False) or getattr(self, "client_url", False)
        if not base_url:
            database_name = getattr(self, "database_name", False)
            if database_name:
                base_url = "http://%s" % database_name
        if not base_url:
            return False
        if not base_url.startswith(("http://", "https://")):
            base_url = "http://%s" % base_url
        return base_url.rstrip("/") + "/web/login"

    def _auto_restart_client(self):
        self.ensure_one()
        wizard = self.env["saas.bulk.restart.wizard"].create({})
        restart_method_name = wizard._find_restart_method_name(self)
        self.write({
            "health_state": "restarting",
            "last_auto_restart": fields.Datetime.now(),
            "auto_restart_attempt_count": self.auto_restart_attempt_count + 1,
            "health_message": _("Auto restart requested."),
        })
        self._log_health_event(
            "auto_restart",
            health_state="restarting",
            message=_("Automatic restart requested after failed health checks."),
        )
        getattr(self, restart_method_name)()
        if hasattr(self, "message_post"):
            self.message_post(
                body=_("Automatic restart requested after failed health checks.")
            )

    def _log_health_event(self, event_type, health_state=False, http_status=0, url=False, message=False):
        self.ensure_one()
        self.env["saas.client.health.log"].sudo().create({
            "client_id": self.id,
            "event_type": event_type,
            "health_state": health_state or self.health_state,
            "http_status": http_status or 0,
            "failure_count": self.consecutive_failure_count,
            "auto_restart_attempt_count": self.auto_restart_attempt_count,
            "url": url or self._get_health_url(),
            "message": message or self.health_message,
            "user_id": self.env.user.id,
        })
