from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from northstar_api.database import Base
from northstar_api.lead_crm.audit_models import IntegrationAuditEvent
from northstar_api.lead_crm.channel_models import ChannelConnection
from northstar_api.lead_crm.channel_scope import WorkspaceChannelConnection
from northstar_api.lead_crm.models import RawWebhookEvent
from northstar_api.models import (
    Agent,
    OutboxEvent,
    ProcessedEvent,
    Role,
    Tenant,
    User,
    Workspace,
    WorkspaceRole,
)
from northstar_api.routers.channel_webhook_events import requeue_failed_channel_webhook
from northstar_api.security import Principal


@pytest.fixture
async def failed_webhook_requeue_case() -> AsyncIterator[
    tuple[AsyncSession, Principal, dict[str, UUID]]
]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        tenant = Tenant(slug=f"failed-requeue-{uuid4().hex}", name="Failed webhook requeue")
        user = User(
            email=f"failed-requeue-{uuid4().hex}@example.test",
            name="Channel Admin",
            password_hash="test-only",
            is_active=True,
        )
        session.add_all([tenant, user])
        await session.flush()

        workspace = Workspace(
            tenant_id=tenant.id,
            name="Primary workspace",
            slug=f"primary-{uuid4().hex[:8]}",
            created_by=user.id,
        )
        other_workspace = Workspace(
            tenant_id=tenant.id,
            name="Other workspace",
            slug=f"other-{uuid4().hex[:8]}",
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

        connection = ChannelConnection(
            tenant_id=tenant.id,
            provider="telegram",
            name="Primary Telegram",
            status="configuration_error",
            configuration_json={"agentId": str(agent.id)},
            last_error="Channel connection must configure a valid agentId",
        )
        invalid_connection = ChannelConnection(
            tenant_id=tenant.id,
            provider="slack",
            name="Invalid Slack",
            status="configuration_error",
            configuration_json={},
        )
        disabled_connection = ChannelConnection(
            tenant_id=tenant.id,
            provider="instagram",
            name="Disabled Instagram",
            status="disabled",
            configuration_json={"agentId": str(agent.id)},
        )
        other_connection = ChannelConnection(
            tenant_id=tenant.id,
            provider="telegram",
            name="Other Telegram",
            status="configuration_error",
            configuration_json={"agentId": str(other_agent.id)},
        )
        session.add_all(
            [connection, invalid_connection, disabled_connection, other_connection]
        )
        await session.flush()
        session.add_all(
            [
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
                    connection_id=invalid_connection.id,
                ),
                WorkspaceChannelConnection(
                    tenant_id=tenant.id,
                    workspace_id=workspace.id,
                    agent_id=agent.id,
                    connection_id=disabled_connection.id,
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

        received_at = datetime.now(UTC) - timedelta(minutes=20)

        def raw_event(
            channel: ChannelConnection,
            *,
            last_error: str,
            suffix: str,
        ) -> RawWebhookEvent:
            return RawWebhookEvent(
                tenant_id=tenant.id,
                connection_key=str(channel.id),
                provider=channel.provider,
                external_event_id=f"failed-requeue-{suffix}",
                event_type="message.received",
                payload_json={"text": f"private message {suffix}"},
                headers_json={"authorization": f"Bearer secret-{suffix}"},
                payload_hash=(suffix[0] * 64)[:64],
                verification_status="verified",
                processing_status="failed",
                attempt_count=2,
                received_at=received_at,
                last_error=last_error,
                correlation_id=f"private-correlation-{suffix}",
            )

        replayable = raw_event(
            connection,
            last_error="agent_not_configured",
            suffix="a-replayable",
        )
        non_replayable = raw_event(
            connection,
            last_error="provider_runtime_failure",
            suffix="b-nonreplayable",
        )
        invalid_agent = raw_event(
            invalid_connection,
            last_error="agent_not_configured",
            suffix="c-invalid-agent",
        )
        disabled = raw_event(
            disabled_connection,
            last_error="agent_not_configured",
            suffix="d-disabled",
        )
        other_workspace_event = raw_event(
            other_connection,
            last_error="agent_not_configured",
            suffix="e-other-workspace",
        )
        session.add_all(
            [replayable, non_replayable, invalid_agent, disabled, other_workspace_event]
        )
        await session.flush()

        old_processed_event_id = uuid4()
        session.add(
            ProcessedEvent(
                event_id=old_processed_event_id,
                consumer="channel-lead-router-v1",
            )
        )
        await session.commit()

        principal = Principal(
            user_id=user.id,
            tenant_id=tenant.id,
            role=Role.ADMIN,
            token_id="failed-webhook-requeue-test",
            workspace_id=workspace.id,
            workspace_role=WorkspaceRole.ADMIN,
            permissions=frozenset({"integrations.view", "integrations.manage", "audit.view"}),
        )
        yield session, principal, {
            "replayable": replayable.id,
            "non_replayable": non_replayable.id,
            "invalid_agent": invalid_agent.id,
            "disabled": disabled.id,
            "other_workspace": other_workspace_event.id,
            "connection": connection.id,
            "agent": agent.id,
            "old_processed_event": old_processed_event_id,
        }

    await engine.dispose()


async def test_replayable_failed_webhook_uses_existing_outbox_and_preserves_history(
    failed_webhook_requeue_case,
) -> None:
    session, principal, ids = failed_webhook_requeue_case

    before_processed_count = int(
        await session.scalar(select(func.count()).select_from(ProcessedEvent)) or 0
    )
    before_outbox_count = int(
        await session.scalar(select(func.count()).select_from(OutboxEvent)) or 0
    )

    result = await requeue_failed_channel_webhook(ids["replayable"], principal, session)

    assert result.processing_status == "received"
    assert result.error_code is None
    assert result.can_requeue is False
    assert result.attempt_count == 2
    assert result.processed_at is None

    raw = await session.get(RawWebhookEvent, ids["replayable"])
    assert raw is not None
    assert raw.processing_status == "received"
    assert raw.attempt_count == 2
    assert raw.processed_at is None
    assert raw.last_error is None
    assert raw.payload_json == {"text": "private message a-replayable"}

    after_processed_count = int(
        await session.scalar(select(func.count()).select_from(ProcessedEvent)) or 0
    )
    assert after_processed_count == before_processed_count
    assert await session.get(
        ProcessedEvent,
        (ids["old_processed_event"], "channel-lead-router-v1"),
    ) is not None

    outbox_rows = list(
        await session.scalars(
            select(OutboxEvent).where(
                OutboxEvent.aggregate_type == "raw_webhook_event",
                OutboxEvent.aggregate_id == str(ids["replayable"]),
                OutboxEvent.event_type == "channel.event.received.v1",
            )
        )
    )
    assert len(outbox_rows) == 1
    assert before_outbox_count + 1 == int(
        await session.scalar(select(func.count()).select_from(OutboxEvent)) or 0
    )
    replay = outbox_rows[0]
    assert replay.published_at is None
    assert replay.payload == {
        "rawEventId": str(ids["replayable"]),
        "provider": "telegram",
        "workspaceId": str(principal.workspace_id),
        "agentId": str(ids["agent"]),
        "channelConnectionId": str(ids["connection"]),
    }

    audit = await session.scalar(
        select(IntegrationAuditEvent).where(
            IntegrationAuditEvent.action == "channel.webhook.failed_requeued",
            IntegrationAuditEvent.entity_id == str(ids["replayable"]),
        )
    )
    assert audit is not None
    assert audit.tenant_id == principal.tenant_id
    assert audit.workspace_id == principal.workspace_id
    assert audit.actor_user_id == principal.user_id
    assert audit.category == "channel"
    assert audit.severity == "warning"
    assert audit.before_json == {
        "processingStatus": "failed",
        "errorCode": "agent_not_configured",
        "attemptCount": 2,
    }
    assert audit.after_json == {
        "processingStatus": "received",
        "errorCode": None,
        "attemptCount": 2,
    }
    assert audit.metadata_json == {
        "connectionId": str(ids["connection"]),
        "provider": "telegram",
        "agentId": str(ids["agent"]),
    }
    rendered_audit = str(audit.before_json) + str(audit.after_json) + str(audit.metadata_json)
    assert "private message" not in rendered_audit
    assert "Bearer" not in rendered_audit
    assert "private-correlation" not in rendered_audit


async def test_non_replayable_failed_webhook_is_not_requeued(failed_webhook_requeue_case) -> None:
    session, principal, ids = failed_webhook_requeue_case

    with pytest.raises(HTTPException) as exc_info:
        await requeue_failed_channel_webhook(ids["non_replayable"], principal, session)
    assert exc_info.value.status_code == 409

    raw = await session.get(RawWebhookEvent, ids["non_replayable"])
    assert raw is not None
    assert raw.processing_status == "failed"
    assert raw.last_error == "provider_runtime_failure"


async def test_failed_webhook_requeue_does_not_cross_workspace(failed_webhook_requeue_case) -> None:
    session, principal, ids = failed_webhook_requeue_case

    with pytest.raises(HTTPException) as exc_info:
        await requeue_failed_channel_webhook(ids["other_workspace"], principal, session)
    assert exc_info.value.status_code == 404

    raw = await session.get(RawWebhookEvent, ids["other_workspace"])
    assert raw is not None
    assert raw.processing_status == "failed"


async def test_failed_webhook_requeue_requires_corrected_agent_configuration(
    failed_webhook_requeue_case,
) -> None:
    session, principal, ids = failed_webhook_requeue_case

    with pytest.raises(HTTPException) as exc_info:
        await requeue_failed_channel_webhook(ids["invalid_agent"], principal, session)
    assert exc_info.value.status_code == 409

    raw = await session.get(RawWebhookEvent, ids["invalid_agent"])
    assert raw is not None
    assert raw.processing_status == "failed"
    assert raw.last_error == "agent_not_configured"


async def test_failed_webhook_requeue_requires_enabled_connection(
    failed_webhook_requeue_case,
) -> None:
    session, principal, ids = failed_webhook_requeue_case

    with pytest.raises(HTTPException) as exc_info:
        await requeue_failed_channel_webhook(ids["disabled"], principal, session)
    assert exc_info.value.status_code == 409

    raw = await session.get(RawWebhookEvent, ids["disabled"])
    assert raw is not None
    assert raw.processing_status == "failed"
