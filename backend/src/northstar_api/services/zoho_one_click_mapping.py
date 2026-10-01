from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.lead_crm.connectors import CRMFieldDefinition
from northstar_api.lead_crm.models import CRMConnection, CRMFieldMapping, CRMFieldSchema


def schema_hash(fields: list[CRMFieldDefinition]) -> str:
    serializable = [
        {
            "apiName": field.api_name,
            "type": field.data_type,
            "required": field.required,
            "readOnly": field.read_only,
            "picklist": list(field.picklist_values),
        }
        for field in sorted(fields, key=lambda item: item.api_name)
    ]
    return hashlib.sha256(
        json.dumps(serializable, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _constant_for_required_field(
    field: CRMFieldDefinition,
    *,
    certification_email: str,
) -> Any | None:
    kind = field.data_type.strip().lower().replace("_", "")
    if field.picklist_values:
        value = next((item for item in field.picklist_values if item), None)
        if value is None:
            return None
        return [value] if "multi" in kind else value
    if kind in {"boolean", "bool"}:
        return False
    if kind in {"integer", "long", "bigint", "double", "currency", "decimal", "percent"}:
        return 0
    if kind == "date":
        return date.today().isoformat()
    if kind in {"datetime", "timestamp"}:
        return datetime.now(UTC).isoformat()
    if kind == "email":
        return certification_email
    if kind in {"phone", "mobile"}:
        return "+15555550123"
    if kind in {"url", "website"}:
        return "https://example.com"
    if kind in {"text", "textarea", "multiline", "string", "varchar"}:
        return "Northstar Integration"
    return None


def build_default_zoho_mapping(
    fields: list[CRMFieldDefinition],
    *,
    certification_email: str,
) -> tuple[dict[str, Any], list[str]]:
    writable = {field.api_name: field for field in fields if not field.read_only}
    mappings: dict[str, str] = {}
    candidates = (
        ("firstName", "First_Name"),
        ("lastName", "Last_Name"),
        ("email", "Email"),
        ("phone", "Mobile" if "Mobile" in writable else "Phone"),
        ("company", "Company"),
        ("jobTitle", "Designation"),
        ("source.channel", "Lead_Source"),
        ("qualificationReason", "Description"),
    )
    for source, target in candidates:
        if target in writable:
            mappings[source] = target

    targeted = set(mappings.values())
    constants: dict[str, Any] = {}
    unsupported: list[str] = []
    provider_managed = {
        "Owner",
        "Created_By",
        "Modified_By",
        "Created_Time",
        "Modified_Time",
        "$layout_id",
        "id",
    }
    for field in fields:
        if not field.required or field.read_only or field.api_name in targeted:
            continue
        if field.api_name in provider_managed:
            continue
        value = _constant_for_required_field(field, certification_email=certification_email)
        if value is None:
            unsupported.append(field.api_name)
        else:
            constants[field.api_name] = value

    return {
        "fields": mappings,
        "constants": constants,
        "managedBy": "zoho-one-click",
    }, sorted(unsupported)


async def persist_zoho_schema(
    session: AsyncSession,
    *,
    connection: CRMConnection,
    fields: list[CRMFieldDefinition],
    current_schema_hash: str,
) -> None:
    await session.execute(
        delete(CRMFieldSchema).where(
            CRMFieldSchema.tenant_id == connection.tenant_id,
            CRMFieldSchema.connection_id == connection.id,
            CRMFieldSchema.object_name == "Leads",
        )
    )
    for field in fields:
        session.add(
            CRMFieldSchema(
                tenant_id=connection.tenant_id,
                connection_id=connection.id,
                object_name="Leads",
                api_name=field.api_name,
                display_label=field.label,
                data_type=field.data_type,
                required=field.required,
                nullable=field.nullable,
                read_only=field.read_only,
                unique=field.unique,
                custom=field.custom,
                max_length=field.max_length,
                picklist_json={"values": list(field.picklist_values)},
                metadata_json=dict(field.metadata),
                schema_hash=current_schema_hash,
            )
        )


async def persist_zoho_mapping(
    session: AsyncSession,
    *,
    connection: CRMConnection,
    definition: dict[str, Any],
    current_schema_hash: str,
    invalid_targets: list[str],
    unsupported_required: list[str],
) -> CRMFieldMapping:
    mapping = await session.scalar(
        select(CRMFieldMapping).where(
            CRMFieldMapping.tenant_id == connection.tenant_id,
            CRMFieldMapping.connection_id == connection.id,
            CRMFieldMapping.object_name == "Leads",
        )
    )
    valid = not invalid_targets and not unsupported_required
    validation = {
        "valid": valid,
        "invalidTargets": invalid_targets,
        "unsupportedRequiredFields": unsupported_required,
        "validatedAt": datetime.now(UTC).isoformat(),
        "managedBy": "zoho-one-click",
    }
    if mapping is None:
        mapping = CRMFieldMapping(
            tenant_id=connection.tenant_id,
            connection_id=connection.id,
            object_name="Leads",
            version=1,
            status="active" if valid else "invalid",
            mapping_json=definition,
            validation_json=validation,
            schema_hash=current_schema_hash,
        )
        session.add(mapping)
    else:
        mapping.version += 1
        mapping.status = "active" if valid else "invalid"
        mapping.mapping_json = definition
        mapping.validation_json = validation
        mapping.schema_hash = current_schema_hash
    await session.flush()
    return mapping
