from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from northstar_api.lead_crm.connectors import crm_registry
from northstar_api.lead_crm.domain import CRMProvider
from northstar_api.lead_crm.models import CRMConnection
from northstar_api.services.zoho_one_click_common import (
    ZohoOneClickError,
    zoho_connection_context,
)


async def certify_live_zoho(
    connection: CRMConnection,
    *,
    credentials: dict[str, Any],
    definition: dict[str, Any],
) -> dict[str, Any]:
    connector = crm_registry.get(CRMProvider.ZOHO)
    certification_email = f"northstar.crm.cert.{connection.id.hex[:12]}@example.com"
    writable_payload = {
        "Last_Name": "Northstar CRM Certification",
        "Company": "Northstar Integration",
        "Email": certification_email,
        "Description": (
            "Automated Northstar one-click CRM certification record. "
            "It is safe to archive or delete after verification."
        ),
        **dict(definition.get("constants") or {}),
    }
    certification_configuration = {
        **dict(connection.configuration_json or {}),
        "trigger": [],
        "duplicateCheckFields": ["Email"],
    }
    context = zoho_connection_context(
        connection,
        credentials,
        configuration=certification_configuration,
    )
    result = await connector.upsert_lead(
        context,
        writable_payload,
        idempotency_key=f"zoho-certification:{connection.id}",
    )
    if not result.accepted or not result.external_record_id:
        raise ZohoOneClickError("Zoho did not return a durable record acknowledgement")
    read_back = await connector.get_lead(context, result.external_record_id)
    verified_fields: list[str] = []
    for field_name in ("Email", "Last_Name", "Company"):
        expected = writable_payload.get(field_name)
        if expected is not None and str(read_back.get(field_name) or "") == str(expected):
            verified_fields.append(field_name)
    if "Email" not in verified_fields or "Last_Name" not in verified_fields:
        raise ZohoOneClickError("Zoho read-back did not match the certification lead")
    return {
        "status": "verified",
        "externalRecordId": result.external_record_id,
        "providerRequestId": result.provider_request_id,
        "providerCode": result.provider_code,
        "action": result.metadata.get("action"),
        "verifiedFields": verified_fields,
        "verifiedAt": datetime.now(UTC).isoformat(),
        "certificationEmail": certification_email,
    }
