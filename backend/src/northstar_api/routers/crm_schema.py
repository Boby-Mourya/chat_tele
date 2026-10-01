from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.database import get_session
from northstar_api.dependencies import require_permissions
from northstar_api.lead_crm.connectors import CRMConnectionContext, CRMError, crm_registry
from northstar_api.lead_crm.credentials import CredentialStoreError, credential_store
from northstar_api.lead_crm.domain import CRMProvider
from northstar_api.lead_crm.models import CRMConnection, CRMFieldMapping, CRMFieldSchema
from northstar_api.lead_crm.workspace_scope import WorkspaceCRMConnection
from northstar_api.security import Principal

router = APIRouter(tags=["crm"])
DB = Annotated[AsyncSession, Depends(get_session)]
CRMViewPrincipal = Annotated[Principal, Depends(require_permissions("crm.view"))]
CRMManagePrincipal = Annotated[Principal, Depends(require_permissions("crm.manage"))]


def _schema_hash(fields: list[dict[str, Any]]) -> str:
    raw = json.dumps(fields, separators=(",", ":"), sort_keys=True, default=str).encode()
    return hashlib.sha256(raw).hexdigest()


async def _connection_context(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    connection_id: UUID,
) -> tuple[CRMConnection, CRMConnectionContext]:
    connection = await session.scalar(
        select(CRMConnection)
        .join(WorkspaceCRMConnection, WorkspaceCRMConnection.connection_id == CRMConnection.id)
        .where(
            CRMConnection.id == connection_id,
            CRMConnection.tenant_id == tenant_id,
            WorkspaceCRMConnection.tenant_id == tenant_id,
            WorkspaceCRMConnection.workspace_id == workspace_id,
        )
    )
    if not connection:
        raise HTTPException(status_code=404, detail="CRM connection not found in this workspace")
    credentials: dict[str, Any] = {}
    if connection.credentials_encrypted:
        try:
            credentials = credential_store.decrypt(connection.credentials_encrypted)
        except CredentialStoreError as exc:
            raise HTTPException(status_code=409, detail="CRM credentials require reconnection") from exc
    try:
        provider = CRMProvider(connection.provider)
        crm_registry.get(provider)
    except (ValueError, CRMError) as exc:
        raise HTTPException(status_code=409, detail="CRM connector is not available") from exc
    return connection, CRMConnectionContext(
        tenant_id=tenant_id,
        connection_id=connection.id,
        provider=provider,
        configuration=dict(connection.configuration_json or {}),
        credentials=credentials,
    )


async def _assert_scoped_connection(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    connection_id: UUID,
) -> None:
    connection = await session.scalar(
        select(CRMConnection.id)
        .join(WorkspaceCRMConnection, WorkspaceCRMConnection.connection_id == CRMConnection.id)
        .where(
            CRMConnection.id == connection_id,
            CRMConnection.tenant_id == tenant_id,
            WorkspaceCRMConnection.tenant_id == tenant_id,
            WorkspaceCRMConnection.workspace_id == workspace_id,
        )
    )
    if not connection:
        raise HTTPException(status_code=404, detail="CRM connection not found in this workspace")


@router.post("/crm/connections/{connection_id}/schema/refresh")
async def refresh_crm_schema(
    connection_id: UUID,
    principal: CRMManagePrincipal,
    session: DB,
    object_name: str = "Leads",
) -> dict[str, Any]:
    connection, context = await _connection_context(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        connection_id=connection_id,
    )
    connector = crm_registry.get(context.provider)
    try:
        definitions = await connector.discover_schema(context, object_name)
    except CRMError as exc:
        connection.last_error = exc.code.value
        await session.commit()
        raise HTTPException(
            status_code=502 if exc.retryable else 409, detail="CRM schema discovery failed"
        ) from exc
    serialized = [
        {
            "apiName": field.api_name,
            "label": field.label,
            "dataType": field.data_type,
            "required": field.required,
            "nullable": field.nullable,
            "readOnly": field.read_only,
            "unique": field.unique,
            "custom": field.custom,
            "maxLength": field.max_length,
            "picklistValues": list(field.picklist_values),
            "metadata": field.metadata,
        }
        for field in definitions
    ]
    digest = _schema_hash(serialized)
    await session.execute(
        delete(CRMFieldSchema).where(
            CRMFieldSchema.tenant_id == principal.tenant_id,
            CRMFieldSchema.connection_id == connection_id,
            CRMFieldSchema.object_name == object_name,
        )
    )
    for field in definitions:
        session.add(
            CRMFieldSchema(
                tenant_id=principal.tenant_id,
                connection_id=connection_id,
                object_name=object_name,
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
                metadata_json=field.metadata,
                schema_hash=digest,
            )
        )
    mappings = list(
        await session.scalars(
            select(CRMFieldMapping).where(
                CRMFieldMapping.tenant_id == principal.tenant_id,
                CRMFieldMapping.connection_id == connection_id,
                CRMFieldMapping.object_name == object_name,
            )
        )
    )
    for mapping in mappings:
        if mapping.schema_hash and mapping.schema_hash != digest:
            mapping.status = "degraded"
            mapping.validation_json = {
                "valid": False,
                "reason": "schema_drift",
                "previousSchemaHash": mapping.schema_hash,
                "currentSchemaHash": digest,
            }
    connection.last_error = None
    await session.commit()
    return {
        "connectionId": str(connection_id),
        "workspaceId": str(principal.workspace_id),
        "objectName": object_name,
        "schemaHash": digest,
        "fields": serialized,
    }


@router.get("/crm/connections/{connection_id}/schema")
async def get_crm_schema(
    connection_id: UUID,
    principal: CRMViewPrincipal,
    session: DB,
    object_name: str = "Leads",
) -> dict[str, Any]:
    await _assert_scoped_connection(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        connection_id=connection_id,
    )
    fields = list(
        await session.scalars(
            select(CRMFieldSchema)
            .where(
                CRMFieldSchema.tenant_id == principal.tenant_id,
                CRMFieldSchema.connection_id == connection_id,
                CRMFieldSchema.object_name == object_name,
            )
            .order_by(CRMFieldSchema.display_label)
        )
    )
    return {
        "connectionId": str(connection_id),
        "workspaceId": str(principal.workspace_id),
        "objectName": object_name,
        "schemaHash": fields[0].schema_hash if fields else None,
        "fields": [
            {
                "apiName": field.api_name,
                "label": field.display_label,
                "dataType": field.data_type,
                "required": field.required,
                "nullable": field.nullable,
                "readOnly": field.read_only,
                "unique": field.unique,
                "custom": field.custom,
                "maxLength": field.max_length,
                "picklistValues": field.picklist_json.get("values", []),
            }
            for field in fields
        ],
    }


@router.post("/crm/connections/{connection_id}/mappings/validate")
async def validate_crm_mapping(
    connection_id: UUID,
    principal: CRMManagePrincipal,
    session: DB,
    object_name: str = "Leads",
) -> dict[str, Any]:
    connection, _ = await _connection_context(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        connection_id=connection_id,
    )
    mapping = await session.scalar(
        select(CRMFieldMapping).where(
            CRMFieldMapping.tenant_id == principal.tenant_id,
            CRMFieldMapping.connection_id == connection_id,
            CRMFieldMapping.object_name == object_name,
        )
    )
    if not mapping:
        raise HTTPException(status_code=404, detail="CRM field mapping not found")
    fields = list(
        await session.scalars(
            select(CRMFieldSchema).where(
                CRMFieldSchema.tenant_id == principal.tenant_id,
                CRMFieldSchema.connection_id == connection_id,
                CRMFieldSchema.object_name == object_name,
            )
        )
    )
    if not fields and connection.provider not in {"generic_rest", "generic_webhook"}:
        raise HTTPException(status_code=409, detail="Refresh the CRM schema before validating mappings")
    writable = {field.api_name for field in fields if not field.read_only}
    required = {field.api_name for field in fields if field.required and not field.read_only}
    mapped_targets: set[str] = set()
    definition = mapping.mapping_json or {}
    compact = definition.get("fields") if isinstance(definition, dict) and "fields" in definition else definition
    if isinstance(compact, dict):
        mapped_targets.update(str(value) for value in compact.values() if isinstance(value, str))
    elif isinstance(compact, list):
        mapped_targets.update(
            str(rule["target"])
            for rule in compact
            if isinstance(rule, dict) and isinstance(rule.get("target"), str)
        )
    constants = definition.get("constants") if isinstance(definition, dict) else None
    if isinstance(constants, dict):
        mapped_targets.update(str(key) for key in constants)
    unknown = sorted(target for target in mapped_targets if fields and target not in writable)
    missing_required = sorted(required - mapped_targets)
    if connection.provider == "zoho":
        for name in {"First_Name", "Last_Name", "Email", "Mobile", "Company", "Description"}:
            if name in writable:
                missing_required = [value for value in missing_required if value != name]
    valid = not unknown and not missing_required
    current_hash = fields[0].schema_hash if fields else None
    mapping.schema_hash = current_hash
    mapping.status = "active" if valid else "degraded"
    mapping.validation_json = {
        "valid": valid,
        "unknownOrReadOnlyTargets": unknown,
        "missingRequiredTargets": missing_required,
        "schemaHash": current_hash,
        "workspaceId": str(principal.workspace_id),
    }
    if valid and connection.status in {"draft", "connecting", "degraded", "configuration_error"}:
        connection.status = "healthy" if connection.last_health_at else "connecting"
    await session.commit()
    return mapping.validation_json
