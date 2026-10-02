import logging

from odoo import api, models

_logger = logging.getLogger(__name__)


class SaasContract(models.Model):
    _inherit = "saas.contract"

    @api.model
    def client_creation_cron_action(self):
        """
        Version sécurisée du cron Webkul de création des clients SaaS.

        Un contrat draft/open dont le saas.client montre déjà des signes
        de provisioning ne doit jamais être reprovisionné automatiquement.
        """
        IrDefault = self.env["ir.default"].sudo()

        auto_create_client = IrDefault._get(
            "res.config.settings",
            "auto_create_client",
        )

        if not auto_create_client:
            return []

        contracts = self.sudo().search([
            ("state", "in", ["draft", "open"]),
            ("domain_name", "!=", False),
        ])

        _logger.info(
            "SUNAPP CRON29: contrats candidats=%s",
            contracts.ids,
        )

        results = []

        for contract in contracts:
            client = contract.saas_client

            if client:
                provisioned_signals = []

                for field_name in (
                    "client_url",
                    "container_id",
                    "container_name",
                    "container_path",
                    "data_directory_path",
                    "container_port",
                    "container_lport",
                ):
                    if (
                        field_name in client._fields
                        and client[field_name]
                    ):
                        provisioned_signals.append(field_name)

                if (
                    "state" in client._fields
                    and client.state in (
                        "started",
                        "stopped",
                        "inactive",
                    )
                ):
                    provisioned_signals.append(
                        "state=%s" % client.state
                    )

                if provisioned_signals:
                    _logger.warning(
                        "SUNAPP CRON29 SKIP contract=%s id=%s "
                        "client=%s database=%s signals=%s",
                        contract.display_name,
                        contract.id,
                        client.id,
                        client.database_name,
                        ",".join(provisioned_signals),
                    )
                    continue

            try:
                result = contract.create_saas_client()
                results.append(result)

            except Exception:
                _logger.exception(
                    "SUNAPP CRON29: échec create_saas_client "
                    "contract=%s id=%s",
                    contract.display_name,
                    contract.id,
                )

        return results
