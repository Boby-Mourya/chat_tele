from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.lead_crm.audit import record_audit_event
from northstar_api.models import Workspace
from northstar_api.onboarding_contract import BrandingChoiceSave, ProfileSave
from northstar_api.onboarding_models import OrganizationSetup
from northstar_api.security import Principal
from northstar_api.services.outbox import enqueue_event


def setup_response(setup: OrganizationSetup) -> dict[str, Any]:
    return {
        "revision": setup.revision, "profile": setup.profile_json,
        "draft": setup.draft_json, "profileComplete": setup.profile_complete,
        "profileRequired": setup.required, "brandingChoice": setup.branding_choice,
        "choiceAt": setup.choice_at.isoformat() if setup.choice_at else None,
        "catalogGrants": list(setup.catalog_grants), "onboardingVersion": 1,
    }


async def load_setup(session: AsyncSession, principal: Principal, *, lock: bool = False) -> OrganizationSetup:
    query = select(OrganizationSetup).where(OrganizationSetup.tenant_id == principal.tenant_id)
    if lock:
        query = query.with_for_update()
    setup = await session.scalar(query)
    if setup is None:
        raise HTTPException(status_code=409, detail="Organization setup migration is required")
    return setup


def _check_revision(setup: OrganizationSetup, expected: int) -> None:
    if setup.revision != expected:
        raise HTTPException(status_code=409, detail="Setup changed in another session; reload before saving")


def _record(session: AsyncSession, principal: Principal, action: str, revision: int) -> None:
    record_audit_event(
        session, tenant_id=principal.tenant_id, workspace_id=principal.workspace_id,
        actor_user_id=principal.user_id, action=action, entity_type="organization_setup",
        entity_id=str(principal.tenant_id), category="workspace", metadata={"revision": revision},
    )
    enqueue_event(
        session, tenant_id=principal.tenant_id, aggregate_type="organization",
        aggregate_id=principal.tenant_id, event_type=action + ".v1",
        payload={"workspaceId": str(principal.workspace_id) if principal.workspace_id else None,
                 "actorId": str(principal.user_id), "revision": revision},
    )


async def save_profile(session: AsyncSession, principal: Principal, payload: ProfileSave) -> dict[str, Any]:
    if principal.token_id.startswith("api_key:") or not principal.can("organization.profile.update"):
        raise HTTPException(status_code=403, detail="Organization profile permission required")
    setup = await load_setup(session, principal, lock=True)
    _check_revision(setup, payload.expected_revision)
    data = payload.profile.model_dump(by_alias=True, mode="json")
    setup.draft_json = data
    if payload.complete:
        if not setup.profile_complete:
            workspace = await session.scalar(select(Workspace).where(
                Workspace.tenant_id == principal.tenant_id, Workspace.slug == "default",
            ).with_for_update())
            if workspace is not None:
                duplicate = await session.scalar(select(Workspace.id).where(
                    Workspace.tenant_id == principal.tenant_id,
                    Workspace.slug == payload.profile.workspace_slug, Workspace.id != workspace.id,
                ))
                if duplicate is not None:
                    raise HTTPException(status_code=409, detail="Workspace slug is already in use")
                workspace.name = payload.profile.workspace_name.strip()
                workspace.slug = payload.profile.workspace_slug
                workspace.timezone = payload.profile.timezone
                workspace.default_language = payload.profile.preferred_language
                workspace.date_format = payload.profile.date_format
        setup.profile_json = data
        setup.profile_complete = True
    setup.revision += 1
    _record(session, principal, "organization.profile.completed" if payload.complete else "organization.profile.draft_saved", setup.revision)
    await session.commit()
    return setup_response(setup)


async def save_branding_choice(session: AsyncSession, principal: Principal, payload: BrandingChoiceSave) -> dict[str, Any]:
    if principal.token_id.startswith("api_key:") or not principal.can("organization.profile.update") or not principal.can("branding.edit"):
        raise HTTPException(status_code=403, detail="Organization and workspace branding permissions required")
    setup = await load_setup(session, principal, lock=True)
    _check_revision(setup, payload.expected_revision)
    if not setup.profile_complete:
        raise HTTPException(status_code=409, detail="Complete the organization profile first")
    setup.branding_choice = payload.choice
    setup.choice_actor_id = principal.user_id
    setup.choice_at = datetime.now(UTC)
    setup.revision += 1
    _record(session, principal, "organization.branding_choice.changed", setup.revision)
    await session.commit()
    return setup_response(setup)
