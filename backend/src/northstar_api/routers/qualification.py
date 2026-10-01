from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.database import get_session
from northstar_api.dependencies import AdminPrincipal, CurrentPrincipal
from northstar_api.lead_crm.qualification_models import LeadQualificationRule

router = APIRouter(prefix="/lead-qualification", tags=["lead-qualification"])
DB = Annotated[AsyncSession, Depends(get_session)]

ALLOWED_CONDITIONS = {
    "channel",
    "provider",
    "emailAvailable",
    "phoneAvailable",
    "senderExternalIdAvailable",
    "messageContains",
    "minimumMessageLength",
    "campaign",
    "metadataEquals",
}
ALLOWED_ACTIONS = {"createLead", "qualify", "score", "reason", "syncToCRM"}


class QualificationRuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    enabled: bool = True
    priority: int = Field(default=100, ge=0, le=100_000)
    conditions: dict[str, Any] = Field(default_factory=dict)
    actions: dict[str, Any] = Field(default_factory=dict)


class QualificationRulePatch(BaseModel):
    enabled: bool | None = None
    priority: int | None = Field(default=None, ge=0, le=100_000)
    conditions: dict[str, Any] | None = None
    actions: dict[str, Any] | None = None


class QualificationRuleOut(BaseModel):
    id: UUID
    name: str
    enabled: bool
    priority: int
    version: int
    conditions: dict[str, Any]
    actions: dict[str, Any]
    created_at: datetime
    updated_at: datetime


def _validate_payload(conditions: dict[str, Any], actions: dict[str, Any]) -> None:
    unknown_conditions = set(conditions) - ALLOWED_CONDITIONS
    unknown_actions = set(actions) - ALLOWED_ACTIONS
    if unknown_conditions:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported qualification conditions: {', '.join(sorted(unknown_conditions))}",
        )
    if unknown_actions:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported qualification actions: {', '.join(sorted(unknown_actions))}",
        )
    if "score" in actions:
        try:
            score = int(actions["score"])
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail="Qualification score must be an integer") from exc
        if not 0 <= score <= 100:
            raise HTTPException(status_code=422, detail="Qualification score must be between 0 and 100")


def _out(value: LeadQualificationRule) -> QualificationRuleOut:
    return QualificationRuleOut(
        id=value.id,
        name=value.name,
        enabled=value.enabled,
        priority=value.priority,
        version=value.version,
        conditions=value.conditions_json,
        actions=value.actions_json,
        created_at=value.created_at,
        updated_at=value.updated_at,
    )


@router.get("/rules", response_model=list[QualificationRuleOut])
async def list_rules(principal: CurrentPrincipal, session: DB) -> list[QualificationRuleOut]:
    values = list(
        await session.scalars(
            select(LeadQualificationRule)
            .where(LeadQualificationRule.tenant_id == principal.tenant_id)
            .order_by(LeadQualificationRule.priority, LeadQualificationRule.created_at)
        )
    )
    return [_out(value) for value in values]


@router.post("/rules", response_model=QualificationRuleOut, status_code=201)
async def create_rule(
    payload: QualificationRuleCreate,
    principal: AdminPrincipal,
    session: DB,
) -> QualificationRuleOut:
    _validate_payload(payload.conditions, payload.actions)
    duplicate = await session.scalar(
        select(LeadQualificationRule.id).where(
            LeadQualificationRule.tenant_id == principal.tenant_id,
            LeadQualificationRule.name == payload.name,
        )
    )
    if duplicate:
        raise HTTPException(status_code=409, detail="A qualification rule with that name already exists")
    value = LeadQualificationRule(
        tenant_id=principal.tenant_id,
        name=payload.name,
        enabled=payload.enabled,
        priority=payload.priority,
        conditions_json=payload.conditions,
        actions_json=payload.actions,
    )
    session.add(value)
    await session.commit()
    await session.refresh(value)
    return _out(value)


@router.patch("/rules/{rule_id}", response_model=QualificationRuleOut)
async def patch_rule(
    rule_id: UUID,
    payload: QualificationRulePatch,
    principal: AdminPrincipal,
    session: DB,
) -> QualificationRuleOut:
    value = await session.scalar(
        select(LeadQualificationRule).where(
            LeadQualificationRule.id == rule_id,
            LeadQualificationRule.tenant_id == principal.tenant_id,
        )
    )
    if not value:
        raise HTTPException(status_code=404, detail="Qualification rule not found")
    conditions = payload.conditions if payload.conditions is not None else value.conditions_json
    actions = payload.actions if payload.actions is not None else value.actions_json
    _validate_payload(conditions, actions)
    if payload.enabled is not None:
        value.enabled = payload.enabled
    if payload.priority is not None:
        value.priority = payload.priority
    if payload.conditions is not None:
        value.conditions_json = payload.conditions
    if payload.actions is not None:
        value.actions_json = payload.actions
    value.version += 1
    await session.commit()
    await session.refresh(value)
    return _out(value)


@router.delete("/rules/{rule_id}", status_code=204)
async def delete_rule(
    rule_id: UUID,
    principal: AdminPrincipal,
    session: DB,
) -> None:
    value = await session.scalar(
        select(LeadQualificationRule).where(
            LeadQualificationRule.id == rule_id,
            LeadQualificationRule.tenant_id == principal.tenant_id,
        )
    )
    if not value:
        raise HTTPException(status_code=404, detail="Qualification rule not found")
    await session.delete(value)
    await session.commit()
