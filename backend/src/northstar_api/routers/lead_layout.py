from __future__ import annotations

from datetime import date
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response, UploadFile
from pydantic import EmailStr, Field, TypeAdapter, ValidationError
from sqlalchemy import or_, select

from northstar_api.lead_crm.normalization import normalize_identity
from northstar_api.lead_crm.services import lead_domain_service
from northstar_api.lead_layout import (
    KEY,
    LeadLayout,
    column_value,
    csv_bytes,
    parse_template,
    stored_layout,
    xlsx_bytes,
)
from northstar_api.models import Agent, Lead, Workspace
from northstar_api.routers.leads import (
    DB,
    LeadsUpdatePrincipal,
    LeadsViewPrincipal,
    enqueue_crm_sync,
    lead_response,
)
from northstar_api.schemas import APIModel, LeadOut
from northstar_api.services.education_conversation_policy import education_source
from northstar_api.services.outbox import enqueue_event

router = APIRouter(prefix="/leads", tags=["lead-layout"])


async def workspace_for(session, principal, *, lock=False):
    query = select(Workspace).where(
        Workspace.id == principal.workspace_id, Workspace.tenant_id == principal.tenant_id
    )
    workspace = await session.scalar(query.with_for_update() if lock else query)
    if workspace is None:
        raise HTTPException(404, "Workspace not found")
    return workspace


@router.get("/layout", response_model=LeadLayout)
async def get_layout(principal: LeadsViewPrincipal, session: DB):
    return stored_layout(await workspace_for(session, principal))


@router.put("/layout", response_model=LeadLayout)
async def save_layout(payload: LeadLayout, principal: LeadsUpdatePrincipal, session: DB):
    workspace = await workspace_for(session, principal, lock=True)
    if payload.version != stored_layout(workspace).version:
        raise HTTPException(409, "The layout changed. Reload it before saving your changes.")
    payload.version += 1
    workspace.settings_json = {**(workspace.settings_json or {}), KEY: payload.model_dump(mode="json")}
    enqueue_event(
        session,
        tenant_id=principal.tenant_id,
        aggregate_type="workspace",
        aggregate_id=workspace.id,
        event_type="lead.layout.updated.v1",
        payload={
            "workspaceId": str(workspace.id),
            "version": payload.version,
            "actorId": str(principal.user_id),
        },
    )
    await session.commit()
    return payload


@router.post("/layout/template", response_model=LeadLayout)
async def import_template(file: UploadFile, principal: LeadsUpdatePrincipal):
    try:
        return parse_template(file.filename or "", await file.read(2_000_001))
    except (ValueError, ValidationError) as exc:
        raise HTTPException(422, str(exc)) from None
    finally:
        await file.close()


@router.get("/layout/export")
async def export_leads(
    principal: LeadsViewPrincipal,
    session: DB,
    format: Literal["csv", "xlsx"] = "csv",
    search: str = Query(default="", max_length=320),
    status: str = Query(default="", max_length=40),
):
    layout = stored_layout(await workspace_for(session, principal))
    conditions = [Lead.tenant_id == principal.tenant_id, Lead.workspace_id == principal.workspace_id, ~education_source(Lead)]
    if principal.agent_ids is not None:
        conditions.append(Lead.agent_id.in_(principal.agent_ids))
    if status and status != "all":
        conditions.append(Lead.status == status)
    if search.strip():
        pattern = f"%{search.strip()}%"
        conditions.append(or_(Lead.name.ilike(pattern), Lead.email.ilike(pattern), Lead.phone.ilike(pattern)))
    records = (
        await session.execute(
            select(Lead, Agent.name)
            .join(Agent, Agent.id == Lead.agent_id)
            .where(*conditions)
            .order_by(Lead.created_at.desc(), Lead.id)
            .limit(10001)
        )
    ).all()
    if len(records) > 10000:
        raise HTTPException(
            413, "Export supports up to 10,000 matching leads. Narrow the filters and try again."
        )
    columns = [c for c in layout.columns if c.visible]
    rows = [
        [c.label for c in columns],
        *[[column_value(lead, c, agent) for c in columns] for lead, agent in records],
    ]
    data = csv_bytes(rows) if format == "csv" else xlsx_bytes(rows)
    return Response(
        data,
        media_type="text/csv; charset=utf-8"
        if format == "csv"
        else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="northstar-leads.{format}"'},
    )


class LeadDetailsPatch(APIModel):
    name: str | None = Field(default=None, max_length=160)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=80)
    consent: bool | None = None
    fields: dict[str, Any] = Field(default_factory=dict, max_length=64)


@router.patch("/{lead_id}/details", response_model=LeadOut)
async def edit_details(
    lead_id: UUID, payload: LeadDetailsPatch, principal: LeadsUpdatePrincipal, session: DB
):
    layout = stored_layout(await workspace_for(session, principal))
    lead = await session.scalar(
        select(Lead)
        .where(
            Lead.id == lead_id,
            Lead.tenant_id == principal.tenant_id,
            Lead.workspace_id == principal.workspace_id,
            ~education_source(Lead),
            *((Lead.agent_id.in_(principal.agent_ids),) if principal.agent_ids is not None else ()),
        )
        .with_for_update()
    )
    if lead is None:
        raise HTTPException(404, "Lead not found")
    custom = {c.source[7:]: c for c in layout.columns if c.source.startswith("fields.")}
    updates = {}
    for key, value in payload.fields.items():
        column = custom.get(key)
        if column is None:
            raise HTTPException(422, f"Add {key} to the lead layout before editing it")
        if value is None or value == "":
            updates[key] = None
            continue
        try:
            if column.type == "number":
                value = TypeAdapter(float).validate_python(value)
                import math

                if not math.isfinite(value):
                    raise ValueError("finite number required")
            elif column.type == "boolean":
                value = TypeAdapter(bool).validate_python(value)
            elif column.type == "date":
                value = date.fromisoformat(str(value)).isoformat()
            elif not isinstance(value, str) or len(value) > 2000:
                raise ValueError("text must be at most 2000 characters")
        except (ValueError, ValidationError):
            raise HTTPException(422, f"{column.label}: enter a valid {column.type} value") from None
        updates[key] = value
    merged = {**(lead.fields_json or {}), **updates}
    for column in layout.columns:
        if (
            column.required
            and column.source.startswith("fields.")
            and merged.get(column.source[7:]) in (None, "")
        ):
            raise HTTPException(422, f"{column.label} is required")
    changed = payload.model_dump(exclude_unset=True)
    for key in ("name", "email", "phone", "consent"):
        if key in changed:
            if key == "consent" and changed[key] is None:
                raise HTTPException(422, "Consent must be true or false")
            setattr(lead, key, changed[key])
    lead.fields_json = merged
    await session.flush()
    await session.refresh(lead)
    profile = await lead_domain_service.ensure_profile(session, lead=lead)
    profile.custom_fields_json = dict(merged)
    parts = (lead.name or "").split(None, 1)
    profile.first_name = parts[0][:100] if parts else None
    profile.last_name = parts[1][:100] if len(parts) > 1 else None
    identity = normalize_identity(lead.email, lead.phone)
    profile.normalized_email, profile.normalized_phone = identity.email, identity.phone
    profile.consent_status = "granted" if lead.consent else "unknown"
    for key in ("utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content"):
        if key in updates:
            setattr(
                profile,
                key,
                str(updates[key])[: 500 if key == "utm_content" else 240]
                if updates[key] is not None
                else None,
            )
    enqueue_event(
        session,
        tenant_id=lead.tenant_id,
        aggregate_type="lead",
        aggregate_id=lead.id,
        event_type="lead.updated.v1",
        payload={
            "leadId": str(lead.id),
            "workspaceId": str(lead.workspace_id),
            "actorId": str(principal.user_id),
            "changedFields": list(changed),
        },
    )
    enqueue_crm_sync(session, lead, reason="lead_updated")
    await session.commit()
    await session.refresh(lead)
    return lead_response(lead)
