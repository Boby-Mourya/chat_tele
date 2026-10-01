from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from northstar_api.lead_crm.connectors import CRMConnectionContext
from northstar_api.lead_crm.credentials import CredentialStoreError, credential_store
from northstar_api.lead_crm.domain import CRMConnectionStatus, CRMProvider
from northstar_api.lead_crm.models import CRMConnection


class ZohoOneClickError(RuntimeError):
    """A safe, operator-facing one-click Zoho bootstrap failure."""

    def __init__(
        self,
        message: str,
        *,
        connection_status: str = CRMConnectionStatus.DEGRADED.value,
    ) -> None:
        super().__init__(message)
        self.connection_status = connection_status


@dataclass(frozen=True, slots=True)
class ZohoBootstrapResult:
    connection_id: UUID
    mapping_id: UUID
    route_id: UUID
    external_record_id: str | None
    certification_status: str
    verified_fields: tuple[str, ...]


def decrypt_zoho_credentials(connection: CRMConnection) -> dict[str, Any]:
    if not connection.credentials_encrypted:
        return {}
    try:
        return credential_store.decrypt(connection.credentials_encrypted)
    except CredentialStoreError as exc:
        raise ZohoOneClickError(
            "Stored Zoho credentials cannot be decrypted",
            connection_status=CRMConnectionStatus.AUTH_REQUIRED.value,
        ) from exc


def zoho_connection_context(
    connection: CRMConnection,
    credentials: dict[str, Any],
    *,
    configuration: dict[str, Any] | None = None,
) -> CRMConnectionContext:
    return CRMConnectionContext(
        tenant_id=connection.tenant_id,
        connection_id=connection.id,
        provider=CRMProvider.ZOHO,
        configuration=configuration or dict(connection.configuration_json or {}),
        credentials=credentials,
    )
