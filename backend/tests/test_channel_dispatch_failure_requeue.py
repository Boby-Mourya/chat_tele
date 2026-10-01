from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from northstar_api.database import Base
from northstar_api.lead_crm.audit_models import IntegrationAuditEvent
from northstar_api.lead_crm.channel_models import ChannelConnection, ChannelOutboundDelivery
from northstar_api.lead_crm.channel_scope import WorkspaceChannelConnection
from northstar_api.models import (
    Agent,
    Channel,
    Conversation,
    Message,
    MessageRole,
    Role,
    Tenant,
    User,
    Workspace,
    WorkspaceRole,
)
from northstar_api.routers.channel_deliveries import requeue_channel_dispatch_failure
from northstar_api.security import Principal


@pytest.fixture
async def requeue_case() -> AsyncIterator[tuple[AsyncSession, Principal, dict[str, object]]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        tenant = Tenant(slug=f"requeue-{uuid4().hex}", name="Dispatch requeue")
        user = User(
            email=f"channel-requeue-{uuid4().hex}@example.com",
            name="Channel Admin",
            password_hash="test-only",
        )
        session.add_all([tenant, user])
        await session.flush()

        workspace = Workspace(
            tenant_id=tenant.id,
            name="Primary workspace",
            slug=f"primary-requeue-{uuid4().hex[:8]}",
            created_by=user.id,
        )
        other_workspace = Workspace(
            tenant_id=tenant.id,
            name="Other workspace",
            slug=f"other-requeue-{uuid4().hex[:8]}",
            created_by=user.id,
        )
        session.add_all([workspace, other_workspace])
        await session.flush()

        agent = Agent(tenant_id=tenant.id, workspace_id=workspace.id, name="Primary agent")
        other_agent = Agent(
            tenant_id=tenant.id,
            workspace_id=other_workspace.id,
            name="Other agent",
        )
        session.add_all([agent, other_agent])
        await session.flush()

        conversation = Conversation(
            tenant_id=tenant.id,
            workspace_id=workspace.id,
            agent_id=agent.id,
            visitor_id="telegram:42",
            visitor_name="Primary visitor",
            channel=Channel.API,
        )
        other_conversation = Conversation(
            tenant_id=tenant.id,
            workspace_id=other_workspace.id,
            agent_id=other_agent.id,
            visitor_id="slack:C999|1.0",
            visitor_name="Other visitor",
            channel=Channel.API,
        )
        session.add_all([conversation, other_conversation])
        await session.flush()

        messages = [
            Message(
                tenant_id=tenant.id,
                workspace_id=workspace.id,
                conversation_id=conversation.id,
                sequence=index,
                role=MessageRole.ASSISTANT,
                content=f"Outbound {index}",
            )
            for index in range(1, 4)
        ]
        other_message = Message(
            tenant_id=tenant.id,
            workspace_id=other_workspace.id,
            conversation_id=other_conversation.id,
            sequence=1,
            role=MessageRole.ASSISTANT,
            content="Other outbound",
        )
        session.add_all([*messages, other_message])
        await session.flush()

        connection = ChannelConnection(
            tenant_id=tenant.id,
            provider="telegram",
            name="Primary Telegram",
            status="healthy",
            configuration_json={},
        )
        blocked_connection = ChannelConnection(
            tenant_id=tenant.id,
            provider="slack",
            name="Blocked Slack",
            status="reconnect_required",
            configuration_json={},
        )
        other_connection = ChannelConnection(
            tenant_id=tenant.id,
            provider="slack",
            name="Other Slack",
            status="healthy",
            configuration_json={},
        )
        session.add_all([connection, blocked_connection, other_connection])
        await session.flush()
        session.add_all([
            WorkspaceChannelConnection(
                tenant_id=tenant.id,
                workspace_id=workspace.id,
                agent_id=agent.id,
                connection_id=connection.id,
            ),
            WorkspaceChannelConnection(
                tenant_id=tenant.id,
                workspace_id=workspace.id,
                agent_id=agent.id,
                connection_id=blocked_connection.id,
            ),
            WorkspaceChannelConnection(
                tenant_id=tenant.id,
                workspace_id=other_workspace.id,
                agent_id=other_agent.id,
                connection_id=other_connection.id,
            ),
        ])
        await session.flush()

        failed_at = datetime.now(UTC)
        retryable = ChannelOutboundDelivery(
            tenant_id=tenant.id,
            workspace_id=workspace.id,
            connection_id=connection.id,
            message_id=messages[0].id,
            provider="telegram",
            recipient_external_id="42",
            status="dispatch_failed",
            attempt_count=2,
            dispatch_attempts=8,
            dispatched_at=failed_at,
            next_dispatch_at=None,
            last_error="queue dispatch unavailable",
        )
        rejected = ChannelOutboundDelivery(
            tenant_id=tenant.id,
            workspace_id=workspace.id,
            connection_id=connection.id,
            message_id=messages[1].id,
            provider="telegram",
            recipient_external_id="43",
            status="rejected",
            dispatch_attempts=1,
            last_error="provider rejected",
        )
        blocked = ChannelOutboundDelivery(
            tenant_id=tenant.id,
            workspace_id=workspace.id,
            connection_id=blocked_connection.id,
            message_id=messages[2].id,
            provider="slack",
            recipient_external_id="C111|1.0",
            status="dispatch_failed",
            dispatch_attempts=8,
            last_error="queue dispatch unavailable",
        )
        other_delivery = ChannelOutboundDelivery(
            tenant_id=tenant.id,
            workspace_id=other_workspace.id,
            connection_id=other_connection.id,
            message_id=other_message.id,
            provider="slack",
            recipient_external_id="C999|1.0",
            status="dispatch_failed",
            dispatch_attempts=8,
            last_error="queue dispatch unavailable",
        )
        session.add_all([retryable, rejected, blocked, other_delivery])
        await session.commit()

        principal = Principal(
            user_id=user.id,
            tenant_id=tenant.id,
            role=Role.ADMIN,
            token_id="channel-requeue",
            workspace_id=workspace.id,
            workspace_role=WorkspaceRole.ADMIN,
            permissions=frozenset({"integrations.manage", "audit.view"}),
        )
        yield session, principal, {
            "retryable_id": retryable.id,
            "rejected_id": rejected.id,
            "blocked_id": blocked.id,
            "other_id": other_delivery.id,
            "connection_id": connection.id,
        }

    await engine.dispose()


async def test_dispatch_failed_delivery_is_requeued_for_existing_dispatcher(requeue_case) -> None:
    session, principal, ids = requeue_case

    result = await requeue_channel_dispatch_failure(ids["retryable_id"], principal, session)

    assert result.status == "queued"
    assert result.error_code is None
    assert result.attempt_count == 2
    assert result.dispatch_attempts == 0
    assert result.dispatched_at is None
    assert result.next_dispatch_at is not None

    stored = await session.get(ChannelOutboundDelivery, ids["retryable_id"])
    assert stored is not None
    assert stored.status == "queued"
    assert stored.dispatch_attempts == 0
    assert stored.attempt_count == 2
    assert stored.dispatched_at is None
    assert stored.next_dispatch_at is not None
    assert stored.last_error is None

    audit = await session.scalar(
        select(IntegrationAuditEvent).where(
            IntegrationAuditEvent.action == "channel.delivery.dispatch_requeued",
            IntegrationAuditEvent.entity_id == str(ids["retryable_id"]),
        )
    )
    assert audit is not None
    assert audit.tenant_id == principal.tenant_id
    assert audit.workspace_id == principal.workspace_id
    assert audit.actor_user_id == principal.user_id
    assert audit.category == "channel"
    assert audit.severity == "warning"
    assert audit.before_json == {"status": "dispatch_failed", "dispatchAttempts": 8}
    assert audit.after_json["status"] == "queued"
    assert audit.after_json["dispatchAttempts"] == 0
    assert audit.metadata_json["connectionId"] == str(ids["connection_id"])
    assert "recipient" not in str(audit.metadata_json).lower()


async def test_non_dispatch_failure_is_not_manually_requeued(requeue_case) -> None:
    session, principal, ids = requeue_case

    with pytest.raises(HTTPException) as exc_info:
        await requeue_channel_dispatch_failure(ids["rejected_id"], principal, session)
    assert exc_info.value.status_code == 409

    stored = await session.get(ChannelOutboundDelivery, ids["rejected_id"])
    assert stored is not None
    assert stored.status == "rejected"
    assert stored.dispatch_attempts == 1


async def test_requeue_requires_operational_connection(requeue_case) -> None:
    session, principal, ids = requeue_case

    with pytest.raises(HTTPException) as exc_info:
        await requeue_channel_dispatch_failure(ids["blocked_id"], principal, session)
    assert exc_info.value.status_code == 409

    stored = await session.get(ChannelOutboundDelivery, ids["blocked_id"])
    assert stored is not None
    assert stored.status == "dispatch_failed"
    assert stored.dispatch_attempts == 8


async def test_requeue_does_not_cross_workspace_boundary(requeue_case) -> None:
    session, principal, ids = requeue_case

    with pytest.raises(HTTPException) as exc_info:
        await requeue_channel_dispatch_failure(ids["other_id"], principal, session)
    assert exc_info.value.status_code == 404
