from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from northstar_api.database import Base
from northstar_api.lead_crm.channel_models import ChannelConnection, ChannelOutboundDelivery
from northstar_api.lead_crm.channel_scope import WorkspaceChannelConnection
from northstar_api.lead_crm.models import RawWebhookEvent
from northstar_api.models import (
    Agent,
    Channel,
    Conversation,
    Message,
    MessageRole,
    Role,
    Tenant,
    Workspace,
    WorkspaceRole,
)
from northstar_api.routers.channel_operations import channel_operational_health
from northstar_api.security import Principal


@pytest.fixture
async def channel_operations_case() -> AsyncIterator[tuple[AsyncSession, Principal]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        tenant = Tenant(slug=f"channel-ops-{uuid4().hex}", name="Channel operations")
        session.add(tenant)
        await session.flush()

        workspace = Workspace(
            tenant_id=tenant.id,
            name="Primary workspace",
            slug=f"primary-channel-{uuid4().hex[:8]}",
        )
        other_workspace = Workspace(
            tenant_id=tenant.id,
            name="Other workspace",
            slug=f"other-channel-{uuid4().hex[:8]}",
        )
        session.add_all([workspace, other_workspace])
        await session.flush()

        agent = Agent(tenant_id=tenant.id, workspace_id=workspace.id, name="Primary channel agent")
        other_agent = Agent(
            tenant_id=tenant.id,
            workspace_id=other_workspace.id,
            name="Other channel agent",
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
            visitor_id="slack:C123|1.2",
            visitor_name="Other visitor",
            channel=Channel.API,
        )
        session.add_all([conversation, other_conversation])
        await session.flush()

        primary_messages = [
            Message(
                tenant_id=tenant.id,
                workspace_id=workspace.id,
                conversation_id=conversation.id,
                sequence=index,
                role=MessageRole.ASSISTANT,
                content=f"Primary outbound {index}",
            )
            for index in range(1, 7)
        ]
        other_message = Message(
            tenant_id=tenant.id,
            workspace_id=other_workspace.id,
            conversation_id=other_conversation.id,
            sequence=1,
            role=MessageRole.ASSISTANT,
            content="Other outbound",
        )
        session.add_all([*primary_messages, other_message])
        await session.flush()

        primary_connection = ChannelConnection(
            tenant_id=tenant.id,
            provider="telegram",
            name="Primary Telegram",
            status="healthy",
            configuration_json={},
        )
        other_connection = ChannelConnection(
            tenant_id=tenant.id,
            provider="slack",
            name="Other Slack",
            status="unhealthy",
            last_error="Other workspace failure must not leak",
            configuration_json={},
        )
        session.add_all([primary_connection, other_connection])
        await session.flush()
        session.add_all(
            [
                WorkspaceChannelConnection(
                    tenant_id=tenant.id,
                    workspace_id=workspace.id,
                    agent_id=agent.id,
                    connection_id=primary_connection.id,
                ),
                WorkspaceChannelConnection(
                    tenant_id=tenant.id,
                    workspace_id=other_workspace.id,
                    agent_id=other_agent.id,
                    connection_id=other_connection.id,
                ),
            ]
        )
        await session.flush()

        statuses = ["queued", "processing", "failed", "rejected", "sent"]
        for message, status in zip(primary_messages[:5], statuses, strict=True):
            session.add(
                ChannelOutboundDelivery(
                    tenant_id=tenant.id,
                    workspace_id=workspace.id,
                    connection_id=primary_connection.id,
                    message_id=message.id,
                    provider="telegram",
                    recipient_external_id="42",
                    status=status,
                )
            )
        session.add(
            ChannelOutboundDelivery(
                tenant_id=tenant.id,
                workspace_id=other_workspace.id,
                connection_id=other_connection.id,
                message_id=other_message.id,
                provider="slack",
                recipient_external_id="C123|1.2",
                status="dispatch_failed",
            )
        )
        # Deliberately malformed legacy-style row: it references the active
        # Workspace connection but is stamped with another Workspace. The
        # operations endpoint must exclude it through delivery.workspace_id.
        session.add(
            ChannelOutboundDelivery(
                tenant_id=tenant.id,
                workspace_id=other_workspace.id,
                connection_id=primary_connection.id,
                message_id=primary_messages[-1].id,
                provider="telegram",
                recipient_external_id="99",
                status="dispatch_failed",
            )
        )

        now = datetime.now(UTC)
        session.add_all(
            [
                RawWebhookEvent(
                    tenant_id=tenant.id,
                    connection_key=str(primary_connection.id),
                    provider="telegram",
                    external_event_id="primary-received",
                    event_type="message.received",
                    payload_json={"text": "private pending message", "token": "secret-token"},
                    headers_json={"authorization": "Bearer private"},
                    payload_hash="a" * 64,
                    verification_status="verified",
                    processing_status="received",
                    attempt_count=0,
                    received_at=now,
                    correlation_id="corr-primary-received",
                ),
                RawWebhookEvent(
                    tenant_id=tenant.id,
                    connection_key=str(primary_connection.id),
                    provider="telegram",
                    external_event_id="primary-stale",
                    event_type="message.received",
                    payload_json={"text": "private stale message", "secret": "stale-secret"},
                    headers_json={"x-private": "stale-header"},
                    payload_hash="b" * 64,
                    verification_status="verified",
                    processing_status="received",
                    attempt_count=0,
                    received_at=now - timedelta(minutes=10),
                    correlation_id="corr-primary-stale",
                ),
                RawWebhookEvent(
                    tenant_id=tenant.id,
                    connection_key=str(primary_connection.id),
                    provider="telegram",
                    external_event_id="primary-failed",
                    event_type="message.received",
                    payload_json={"text": "private failed message"},
                    headers_json={"x-secret": "private-header"},
                    payload_hash="c" * 64,
                    verification_status="verified",
                    processing_status="failed",
                    attempt_count=2,
                    received_at=now,
                    last_error="raw provider failure must not leak",
                    correlation_id="corr-primary-failed",
                ),
                RawWebhookEvent(
                    tenant_id=tenant.id,
                    connection_key=str(primary_connection.id),
                    provider="telegram",
                    external_event_id="primary-rejected",
                    event_type="message.received",
                    payload_json={"private": "rejected content"},
                    headers_json={},
                    payload_hash="d" * 64,
                    verification_status="verified",
                    processing_status="rejected",
                    attempt_count=1,
                    received_at=now,
                    last_error="plan entitlement: channel_not_allowed",
                    correlation_id="corr-primary-rejected",
                ),
                RawWebhookEvent(
                    tenant_id=tenant.id,
                    connection_key=str(primary_connection.id),
                    provider="telegram",
                    external_event_id="primary-processed",
                    event_type="message.received",
                    payload_json={"private": "processed content"},
                    headers_json={},
                    payload_hash="e" * 64,
                    verification_status="verified",
                    processing_status="processed",
                    attempt_count=1,
                    received_at=now,
                    processed_at=now,
                    correlation_id="corr-primary-processed",
                ),
                RawWebhookEvent(
                    tenant_id=tenant.id,
                    connection_key=str(other_connection.id),
                    provider="slack",
                    external_event_id="other-failed",
                    event_type="message.received",
                    payload_json={"private": "other workspace"},
                    headers_json={"authorization": "other-secret"},
                    payload_hash="f" * 64,
                    verification_status="verified",
                    processing_status="failed",
                    attempt_count=9,
                    received_at=now,
                    last_error="Other workspace webhook failure must not leak",
                    correlation_id="corr-other-failed",
                ),
            ]
        )
        await session.commit()

        principal = Principal(
            user_id=uuid4(),
            tenant_id=tenant.id,
            role=Role.MEMBER,
            token_id="channel-ops",
            workspace_id=workspace.id,
            workspace_role=WorkspaceRole.MANAGER,
            permissions=frozenset({"integrations.view"}),
        )
        yield session, principal

    await engine.dispose()


async def test_channel_operational_health_aggregates_only_active_workspace(
    channel_operations_case,
) -> None:
    session, principal = channel_operations_case

    result = await channel_operational_health(principal, session)

    assert result.overall_status == "attention"
    assert result.connection_count == 1
    assert result.healthy_connections == 0
    assert result.attention_connections == 1
    assert result.pending_deliveries == 2
    assert result.retrying_deliveries == 1
    assert result.failed_deliveries == 1
    assert result.pending_webhook_events == 2
    assert result.failed_webhook_events == 1
    assert result.rejected_webhook_events == 1
    assert result.stale_webhook_events == 1
    assert len(result.connections) == 1

    connection = result.connections[0]
    assert connection.name == "Primary Telegram"
    assert connection.provider == "telegram"
    assert connection.pending_deliveries == 2
    assert connection.retrying_deliveries == 1
    assert connection.failed_deliveries == 1
    assert connection.pending_webhook_events == 2
    assert connection.failed_webhook_events == 1
    assert connection.rejected_webhook_events == 1
    assert connection.stale_webhook_events == 1
    rendered = str(result.model_dump(mode="json"))
    for forbidden in (
        "secret-token",
        "stale-secret",
        "stale-header",
        "private stale message",
        "private-header",
        "private pending message",
        "private failed message",
        "raw provider failure",
        "channel_not_allowed",
        "other workspace",
        "Other workspace",
    ):
        assert forbidden not in rendered


async def test_stale_received_webhook_requires_attention(channel_operations_case) -> None:
    session, principal = channel_operations_case

    terminal_delivery = await session.scalar(
        select(ChannelOutboundDelivery).where(
            ChannelOutboundDelivery.tenant_id == principal.tenant_id,
            ChannelOutboundDelivery.workspace_id == principal.workspace_id,
            ChannelOutboundDelivery.status == "rejected",
        )
    )
    failed_event = await session.scalar(
        select(RawWebhookEvent).where(
            RawWebhookEvent.tenant_id == principal.tenant_id,
            RawWebhookEvent.correlation_id == "corr-primary-failed",
        )
    )
    assert terminal_delivery is not None
    assert failed_event is not None
    terminal_delivery.status = "sent"
    failed_event.processing_status = "processed"
    await session.commit()

    result = await channel_operational_health(principal, session)

    assert result.failed_deliveries == 0
    assert result.failed_webhook_events == 0
    assert result.stale_webhook_events == 1
    assert result.attention_connections == 1
    assert result.overall_status == "attention"


async def test_rejected_and_fresh_pending_webhooks_do_not_become_health_failures(
    channel_operations_case,
) -> None:
    session, principal = channel_operations_case

    terminal_delivery = await session.scalar(
        select(ChannelOutboundDelivery).where(
            ChannelOutboundDelivery.tenant_id == principal.tenant_id,
            ChannelOutboundDelivery.workspace_id == principal.workspace_id,
            ChannelOutboundDelivery.status == "rejected",
        )
    )
    failed_event = await session.scalar(
        select(RawWebhookEvent).where(
            RawWebhookEvent.tenant_id == principal.tenant_id,
            RawWebhookEvent.correlation_id == "corr-primary-failed",
        )
    )
    stale_event = await session.scalar(
        select(RawWebhookEvent).where(
            RawWebhookEvent.tenant_id == principal.tenant_id,
            RawWebhookEvent.correlation_id == "corr-primary-stale",
        )
    )
    assert terminal_delivery is not None
    assert failed_event is not None
    assert stale_event is not None
    terminal_delivery.status = "sent"
    failed_event.processing_status = "processed"
    stale_event.processing_status = "processed"
    await session.commit()

    result = await channel_operational_health(principal, session)

    assert result.failed_deliveries == 0
    assert result.failed_webhook_events == 0
    assert result.stale_webhook_events == 0
    assert result.rejected_webhook_events == 1
    assert result.pending_webhook_events == 1
    assert result.attention_connections == 0
    assert result.overall_status == "active"


async def test_channel_operational_health_empty_workspace_is_explicit(
    channel_operations_case,
) -> None:
    session, principal = channel_operations_case
    empty_workspace = Workspace(
        tenant_id=principal.tenant_id,
        name="Empty channel workspace",
        slug=f"empty-channel-{uuid4().hex[:8]}",
    )
    session.add(empty_workspace)
    await session.commit()

    empty_principal = Principal(
        user_id=principal.user_id,
        tenant_id=principal.tenant_id,
        role=principal.role,
        token_id="channel-ops-empty",
        workspace_id=empty_workspace.id,
        workspace_role=WorkspaceRole.MANAGER,
        permissions=frozenset({"integrations.view"}),
    )
    result = await channel_operational_health(empty_principal, session)

    assert result.overall_status == "empty"
    assert result.connection_count == 0
    assert result.pending_webhook_events == 0
    assert result.failed_webhook_events == 0
    assert result.rejected_webhook_events == 0
    assert result.stale_webhook_events == 0
    assert result.connections == []


async def test_channel_operational_health_requires_active_workspace(
    channel_operations_case,
) -> None:
    session, principal = channel_operations_case
    no_workspace = Principal(
        user_id=principal.user_id,
        tenant_id=principal.tenant_id,
        role=principal.role,
        token_id="channel-ops-no-workspace",
        workspace_id=None,
        workspace_role=None,
        permissions=principal.permissions,
    )

    with pytest.raises(HTTPException) as exc_info:
        await channel_operational_health(no_workspace, session)
    assert exc_info.value.status_code == 403
