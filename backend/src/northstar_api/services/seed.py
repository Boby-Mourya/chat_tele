from __future__ import annotations

import re

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.config import Settings
from northstar_api.database import set_tenant_context
from northstar_api.models import (
    Agent,
    AgentStatus,
    Role,
    Tenant,
    TenantMembership,
    User,
    Workspace,
    WorkspaceMembership,
    WorkspaceRole,
)
from northstar_api.onboarding_contract import STARTER_CATALOG
from northstar_api.onboarding_models import OrganizationSetup
from northstar_api.security import hash_password

logger = structlog.get_logger(__name__)


def _slug(value: str) -> str:
    result = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return result[:70] or "workspace"


async def seed_from_environment(session: AsyncSession, settings: Settings) -> None:
    if not settings.seed_admin_email or not settings.seed_admin_password:
        return
    if session.bind and session.bind.dialect.name == "postgresql":
        await session.execute(text("SELECT pg_advisory_xact_lock(hashtext('northstar:environment-seed'))"))
    email = str(settings.seed_admin_email).strip().lower()
    existing = await session.scalar(select(User).where(User.email == email))
    if existing:
        return
    base_slug = _slug(settings.seed_tenant_name)
    tenant = Tenant(name=settings.seed_tenant_name, slug=base_slug, plan=settings.seed_tenant_plan)
    user = User(
        email=email,
        name=settings.seed_admin_name,
        password_hash=hash_password(settings.seed_admin_password.get_secret_value()),
    )
    session.add_all([tenant, user])
    await session.flush()
    await set_tenant_context(session, tenant.id)
    workspace = Workspace(
        tenant_id=tenant.id,
        name=settings.seed_tenant_name,
        slug="default",
        created_by=user.id,
    )
    session.add(workspace)
    await session.flush()
    session.add(TenantMembership(tenant_id=tenant.id, user_id=user.id, role=Role.OWNER))
    session.add(
        WorkspaceMembership(
            tenant_id=tenant.id,
            workspace_id=workspace.id,
            user_id=user.id,
            role=WorkspaceRole.ADMIN,
            all_agents_access=True,
        )
    )
    session.add(
        OrganizationSetup(
            tenant_id=tenant.id,
            required=False,
            profile_complete=False,
            revision=0,
            profile_json={"displayName": tenant.name},
            draft_json={
                "displayName": tenant.name,
                "workspaceName": workspace.name,
                "contactName": user.name,
                "contactEmail": user.email,
            },
            branding_choice="unseen",
            catalog_grants=[str(item["id"]) for item in STARTER_CATALOG],
        )
    )
    if settings.seed_demo_agent:
        session.add(
            Agent(
                tenant_id=tenant.id,
                workspace_id=workspace.id,
                name="Northstar Guide",
                description="Customer support and product expert",
                status=AgentStatus.ACTIVE,
                instructions=(
                    "Answer with approved knowledge only. Give the direct answer first, stay concise, "
                    "and offer human help when the evidence is incomplete."
                ),
            )
        )
    await session.commit()
    logger.info("environment_seed_created", tenant_id=str(tenant.id), user_id=str(user.id))
