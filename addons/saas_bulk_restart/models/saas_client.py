import logging

import requests
from urllib3.exceptions import InsecureRequestWarning

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)
requests.packages.urllib3.disable_warnings(category=InsecureRequestWarning)


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
            ("gateway_error", "Gateway Error"),
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
    last_http_status = fields.Integer(
        string="Last HTTP Status",
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
    health_summary = fields.Char(
        string="Service",
        compute="_compute_health_summary",
    )
    health_check_url = fields.Char(
        string="URL",
        compute="_compute_health_check_url",
    )
    gateway_error_count = fields.Integer(
        string="502/503/504",
        compute="_compute_health_counters",
    )
    inaccessible_count = fields.Integer(
        string="Inaccessible",
        compute="_compute_health_counters",
    )
    manual_stop_count = fields.Integer(
        string="Stopped",
        compute="_compute_health_counters",
    )
    restart_count = fields.Integer(
        string="Restarted",
        compute="_compute_health_counters",
    )
    blocked_count = fields.Integer(
        string="Blocked",
        compute="_compute_health_counters",
    )

    @api.depends("health_state", "auto_restart_intentional_stop")
    def _compute_health_summary(self):
        labels = {
            "online": _("Accessible"),
            "gateway_error": _("Gateway Error"),
            "offline": _("Inaccessible"),
            "restarting": _("Restarting"),
            "blocked": _("Blocked"),
            "unknown": _("Unknown"),
        }
        for client in self:
            if client.auto_restart_intentional_stop:
                client.health_summary = _("Stopped voluntarily")
            else:
                client.health_summary = labels.get(client.health_state, _("Unknown"))

    def _compute_health_check_url(self):
        for client in self:
            client.health_check_url = client._get_base_health_url() or False

    def _compute_health_counters(self):
        counters = {
            client.id: {
                "gateway_error_count": 0,
                "inaccessible_count": 0,
                "manual_stop_count": 0,
                "restart_count": 0,
                "blocked_count": 0,
            }
            for client in self
        }
        if counters:
            groups = self.env["saas.client.health.log"].sudo().read_group(
                [("client_id", "in", list(counters))],
                ["client_id", "event_type"],
                ["client_id", "event_type"],
                lazy=False,
            )
            for group in groups:
                client_id = group["client_id"][0]
                event_type = group["event_type"]
                count = group["__count"]
                if event_type == "gateway_error":
                    counters[client_id]["gateway_error_count"] += count
                    counters[client_id]["inaccessible_count"] += count
                elif event_type == "health_offline":
                    counters[client_id]["inaccessible_count"] += count
                elif event_type == "manual_stop":
                    counters[client_id]["manual_stop_count"] += count
                elif event_type in ("auto_restart", "manual_restart"):
                    counters[client_id]["restart_count"] += count
                elif event_type == "auto_restart_blocked":
                    counters[client_id]["blocked_count"] += count

        for client in self:
            values = counters.get(client.id, {})
            client.gateway_error_count = values.get("gateway_error_count", 0)
            client.inaccessible_count = values.get("inaccessible_count", 0)
            client.manual_stop_count = values.get("manual_stop_count", 0)
            client.restart_count = values.get("restart_count", 0)
            client.blocked_count = values.get("blocked_count", 0)

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

    def action_auto_restart_check_now(self):
        messages = []
        for client in self:
            result = client._health_check_and_auto_restart()
            messages.append("%s: %s" % (client.display_name, result))
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Auto Restart Check"),
                "message": "\n".join(messages),
                "type": "success",
                "sticky": True,
            },
        }

    def action_reset_auto_restart_block(self):
        for client in self:
            client.write({
                "health_state": "unknown",
                "health_message": False,
                "consecutive_failure_count": 0,
                "auto_restart_attempt_count": 0,
                "last_auto_restart": False,
                "auto_restart_intentional_stop": False,
            })
            client._log_health_event(
                "auto_restart_reset",
                health_state="unknown",
                message=_("Auto restart block reset by %s.") % self.env.user.display_name,
            )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Auto Restart"),
                "message": _("Auto restart counters reset."),
                "type": "success",
            },
        }

    @classmethod
    def _bulk_restart_safe_int(cls, value, default, minimum=False):
        try:
            result = int(value)
        except (TypeError, ValueError):
            result = default
        if minimum is not False:
            result = max(minimum, result)
        return result

    @api.model
    def _cron_auto_restart_unreachable_clients(self, limit=200):
        clients = self.search([
            ("auto_restart_enabled", "=", True),
            ("auto_restart_intentional_stop", "=", False),
        ], limit=limit)
        for client in clients:
            try:
                result = client._health_check_and_auto_restart()
                _logger.info("Auto restart monitor result for %s: %s", client.display_name, result)
            except Exception:
                _logger.exception("Auto restart monitor failed for SaaS client %s", client.display_name)

    def _health_check_and_auto_restart(self):
        self.ensure_one()
        config = self.env["ir.config_parameter"].sudo()
        failure_threshold = self._bulk_restart_safe_int(
            config.get_param("saas_bulk_restart.failure_threshold"), 2, minimum=1
        )
        gateway_failure_threshold = self._bulk_restart_safe_int(
            config.get_param("saas_bulk_restart.gateway_failure_threshold"), 1, minimum=1
        )
        cooldown_minutes = self._bulk_restart_safe_int(
            config.get_param("saas_bulk_restart.cooldown_minutes"), 5, minimum=0
        )
        max_attempts = self._bulk_restart_safe_int(
            config.get_param("saas_bulk_restart.max_attempts"), 3, minimum=1
        )

        is_online = self._check_client_health()
        if is_online:
            self.write({
                "auto_restart_attempt_count": 0,
                "auto_restart_intentional_stop": False,
            })
            return _("online")

        if self.auto_restart_intentional_stop:
            return _("skipped: voluntarily stopped")
        required_failures = (
            gateway_failure_threshold
            if self.health_state == "gateway_error"
            else failure_threshold
        )
        if self.consecutive_failure_count < required_failures:
            return _("waiting: %s/%s failure(s)") % (
                self.consecutive_failure_count,
                required_failures,
            )
        if self.auto_restart_attempt_count >= max_attempts:
            self.write({
                "health_state": "blocked",
                "health_message": _("Auto restart blocked after too many failed attempts."),
            })
            self._log_health_event(
                "auto_restart_blocked",
                message=_("Auto restart blocked after %s failed attempt(s).") % max_attempts,
            )
            return _("blocked: max attempts reached")
        if self.last_auto_restart:
            elapsed = fields.Datetime.now() - self.last_auto_restart
            if elapsed.total_seconds() < cooldown_minutes * 60:
                remaining = int((cooldown_minutes * 60 - elapsed.total_seconds()) / 60) + 1
                return _("cooldown: retry in about %s minute(s)") % remaining

        self._auto_restart_client()
        return _("restart requested")

    def _check_client_health(self):
        self.ensure_one()
        url = self._get_health_url()
        previous_health_state = self.health_state
        previous_failure_count = self.consecutive_failure_count
        if not url:
            self.write({
                "health_state": "unknown",
                "last_health_check": fields.Datetime.now(),
                "last_http_status": 0,
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
            response = requests.get(url, timeout=10, allow_redirects=True, verify=False)
            if response.status_code < 500:
                self.write({
                    "health_state": "online",
                    "last_health_check": fields.Datetime.now(),
                    "last_http_status": response.status_code,
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
            health_state = "gateway_error" if response.status_code in (502, 503, 504) else "offline"
            event_type = "gateway_error" if health_state == "gateway_error" else "health_offline"
        except requests.RequestException as error:
            message = str(error)[:250]
            http_status = 0
            health_state = "offline"
            event_type = "health_offline"

        self.write({
            "health_state": health_state,
            "last_health_check": fields.Datetime.now(),
            "last_http_status": http_status,
            "health_message": message,
            "consecutive_failure_count": self.consecutive_failure_count + 1,
        })
        self._log_health_event(
            event_type,
            health_state=health_state,
            http_status=http_status,
            url=url,
            message=message,
        )
        return False

    def _get_health_url(self):
        self.ensure_one()
        base_url = self._get_base_health_url()
        if not base_url:
            return False
        return base_url.rstrip("/") + "/web/login"

    def _get_base_health_url(self):
        self.ensure_one()
        base_url = False
        for field_name in (
            "url",
            "client_url",
            "server_url",
            "web_url",
            "instance_url",
            "domain",
            "domain_name",
            "database_name",
            "db_name",
        ):
            if field_name in self._fields:
                base_url = self[field_name]
                if base_url:
                    break
        if not base_url:
            return False
        base_url = str(base_url).strip()
        if base_url.startswith(("http://", "https://")):
            return base_url
        return "http://%s" % base_url

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
