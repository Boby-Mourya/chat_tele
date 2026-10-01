from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from northstar_api.database import Base

if TYPE_CHECKING:
    from northstar_api.models import Agent


class AgentPurpose(str, enum.Enum):
    """The authoritative business purpose for an Agent.

    SUPPORT preserves the platform's existing general/support behavior,
    LEAD_GENERATION enables lead qualification + CRM workflows, and EDUCATION
    is reserved for the enrollment-authorized education runtime.
    """

    SUPPORT = "support"
    LEAD_GENERATION = "lead_generation"
    EDUCATION = "education"


class AgentPurposeSetting(Base):
    """One authoritative purpose record per Agent, scoped to its workspace."""

    __tablename__ = "agent_purpose_settings"
    __table_args__ = (
        UniqueConstraint("agent_id", name="uq_agent_purpose_settings_agent"),
        CheckConstraint(
            "purpose IN ('support', 'lead_generation', 'education')",
            name="ck_agent_purpose_settings_purpose",
        ),
        Index(
            "ix_agent_purpose_settings_scope",
            "tenant_id",
            "workspace_id",
            "purpose",
        ),
    )

    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=False
    )
    purpose: Mapped[str] = mapped_column(String(40), nullable=False, default=AgentPurpose.SUPPORT.value)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


async def get_agent_purpose(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID,
) -> AgentPurpose:
    """Return an Agent's purpose, defaulting legacy Agents safely to support."""

    raw = await session.scalar(
        select(AgentPurposeSetting.purpose).where(
            AgentPurposeSetting.tenant_id == tenant_id,
            AgentPurposeSetting.workspace_id == workspace_id,
            AgentPurposeSetting.agent_id == agent_id,
        )
    )
    try:
        return AgentPurpose(raw) if raw else AgentPurpose.SUPPORT
    except ValueError:
        # A malformed legacy row must never accidentally enter a privileged
        # purpose-specific runtime. Support is the compatibility-safe fallback.
        return AgentPurpose.SUPPORT


async def set_agent_purpose(
    session: AsyncSession,
    *,
    agent: Agent,
    purpose: AgentPurpose,
) -> AgentPurposeSetting:
    """Create/update the authoritative purpose record for an Agent."""

    value = await session.scalar(
        select(AgentPurposeSetting).where(AgentPurposeSetting.agent_id == agent.id).with_for_update()
    )
    if value is None:
        value = AgentPurposeSetting(
            agent_id=agent.id,
            tenant_id=agent.tenant_id,
            workspace_id=agent.workspace_id,
            purpose=purpose.value,
        )
        session.add(value)
    else:
        # Keep the scope synchronized with the Agent row. Agents are not
        # currently movable between workspaces, but this makes the invariant
        # explicit if that capability is added later.
        value.tenant_id = agent.tenant_id
        value.workspace_id = agent.workspace_id
        value.purpose = purpose.value
    await session.flush()
    return value
