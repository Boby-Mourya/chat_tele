from __future__ import annotations

from northstar_api.lead_crm.connectors import crm_registry
from northstar_api.lead_crm.providers.generic import GenericRESTConnector, GenericWebhookConnector
from northstar_api.lead_crm.providers.secure_native import (
    SecureDynamics365Connector,
    SecureFreshsalesConnector,
    SecureHubSpotConnector,
    SecurePipedriveConnector,
    SecureSalesforceConnector,
    SecureZohoCRMConnector,
)


def register_default_connectors() -> None:
    connectors = (
        SecureZohoCRMConnector(),
        SecureSalesforceConnector(),
        SecureHubSpotConnector(),
        SecureDynamics365Connector(),
        SecurePipedriveConnector(),
        SecureFreshsalesConnector(),
        GenericRESTConnector(),
        GenericWebhookConnector(),
    )
    registered = set(crm_registry._connectors)  # Internal bootstrap only; avoids re-entering providers().
    for connector in connectors:
        if connector.provider not in registered:
            crm_registry.register(connector)
            registered.add(connector.provider)


__all__ = ["register_default_connectors"]
