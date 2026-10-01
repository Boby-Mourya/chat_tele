from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from northstar_api.database import Base
from northstar_api.lead_crm.channel_models import (
    ChannelConnection,
    ChannelDeliveryAttempt,
    ChannelOutboundDelivery,
)
from northstar_api.lead_crm.channel_scope import WorkspaceChannelConnection
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
from northstar_api.routers.channel_deliveries import list_channel_delivery_attempts
from northstar_api.security import Principal


@pytest.fixture
async def attempt_history_case() -> AsyncIterator[tuple[AsyncSession, Principal, dict[str, object]]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        tenant = Tenant(slug=f"channel-attempt-{uuid4().hex}", name="Channel attempts")
        session.add(tenant)
        await session.flush()

        workspace = Workspace(
            tenant_id=tenant.id,
            name="Primary workspace",
            slug=f"channel-attempt-primary-{uuid4().hex[:8]}",
        )
        other_workspace = Workspace(
            tenant_id=tenant.id,
            name="Other workspace",
            slug=f"channel-attempt-other-{uuid4().hex[:8]}",
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
            visitor_id="telegram:attempt-primary",
            visitor_name="Primary visitor",
            channel=Channel.API,
        )
        other_conversation = Conversation(
            tenant_id=tenant.id,
            workspace_id=other_workspace.id,
            agent_id=other_agent.id,
            visitor_id="slack:attempt-other",
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
                content=f"Private attempt message {index}",
            )
            for index in range(1, 4)
        ]
        other_message = Message(
            tenant_id=tenant.id,
            workspace_id=other_workspace.id,
            conversation_id=other_conversation.id,
            sequence=1,
            role=MessageRole.ASSISTANT,
            content="Other workspace private message",
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
        other_connection = ChannelConnection(
            tenant_id=tenant.id,
            provider="slack",
            name="Other Slack",
            status="healthy",
            configuration_json={},
        )
        session.add_all([connection, other_connection])
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
                workspace_id=other_workspace.id,
                agent_id=other_agent.id,
                connection_id=other_connection.id,
            ),
        ])
        await session.flush()

        delivery = ChannelOutboundDelivery(
            tenant_id=tenant.id,
            workspace_id=workspace.id,
            connection_id=connection.id,
            message_id=messages[0].id,
            provider="telegram",
            recipient_external_id="private-recipient-42",
            provider_message_ids=["provider-secret-id"],
            status="failed",
            last_error="Bearer raw-secret provider response",
        )
        disconnected = ChannelOutboundDelivery(
            tenant_id=tenant.id,
            workspace_id=workspace.id,
            connection_id=None,
            message_id=messages[1].id,
            provider="telegram",
            recipient_external_id="private-recipient-43",
            status="dispatch_failed",
        )
        malformed = ChannelOutboundDelivery(
            tenant_id=tenant.id,
            workspace_id=workspace.id,
            connection_id=other_connection.id,
            message_id=messages[2].id,
            provider="slack",
            recipient_external_id="other-private-recipient",
            status="failed",
        )
        other_delivery = ChannelOutboundDelivery(
            tenant_id=tenant.id,
            workspace_id=other_workspace.id,
            connection_id=other_connection.id,
            message_id=other_message.id,
            provider="slack",
            recipient_external_id="other-workspace-recipient",
            status="failed",
        )
        session.add_all([delivery, disconnected, malformed, other_delivery])
        await session.flush()

        now = datetime.now(UTC)
        session.add_all([
            ChannelDeliveryAttempt(
                tenant_id=tenant.id,
                workspace_id=workspace.id,
                delivery_id=delivery.id,
                phase="provider",
                attempt_number=2,
                outcome="failed",
                error_code="provider_retryable",
                created_at=now + timedelta(seconds=2),
            ),
            ChannelDeliveryAttempt(
                tenant_id=tenant.id,
                workspace_id=workspace.id,
                delivery_id=delivery.id,
                phase="dispatch",
                attempt_number=1,
                outcome="published",
                error_code=None,
                created_at=now,
            ),
            ChannelDeliveryAttempt(
                tenant_id=tenant.id,
                workspace_id=workspace.id,
                delivery_id=disconnected.id,
                phase="dispatch",
                attempt_number=8,
                outcome="publish_failed",
                error_code="broker_publish_failed",
                created_at=now + timedelta(seconds=1),
            ),
            ChannelDeliveryAttempt(
                tenant_id=tenant.id,
                workspace_id=workspace.id,
                delivery_id=malformed.id,
                phase="provider",
                attempt_number=1,
                outcome="rejected",
                error_code="provider_rejected",
                created_at=now,
            ),
            ChannelDeliveryAttempt(
                tenant_id=tenant.id,
                workspace_id=other_workspace.id,
                delivery_id=other_delivery.id,
                phase="provider",
                attempt_number=1,
                outcome="failed",
                error_code="provider_retryable",
                created_at=now,
            ),
        ])
        await session.commit()

        principal = Principal(
            user_id=uuid4(),
            tenant_id=tenant.id,
            role=Role.MEMBER,
            token_id="channel-attempt-history",
            workspace_id=workspace.id,
            workspace_role=WorkspaceRole.MANAGER,
            permissions=frozenset({"integrations.view"}),
        )
        yield session, principal, {
            "delivery_id": delivery.id,
            "disconnected_id": disconnected.id,
            "malformed_id": malformed.id,
            "other_delivery_id": other_delivery.id,
        }

    await engine.dispose()


async def test_channel_attempt_history_is_safe_ordered_and_limited(attempt_history_case) -> None:
    session, principal, ids = attempt_history_case

    attempts = await list_channel_delivery_attempts(
        ids["delivery_id"],
        principal,
        session,
        limit=2,
    )

    assert [attempt.phase for attempt in attempts] == ["provider", "dispatch"]
    assert attempts[0].attempt_number == 2
    assert attempts[0].outcome == "failed"
    assert attempts[0].error_code == "provider_retryable"
    assert attempts[1].outcome == "published"

    serialized = [attempt.model_dump(mode="json") for attempt in attempts]
    assert set(serialized[0]) == {
        "id",
        "delivery_id",
        "phase",
        "attempt_number",
        "outcome",
        "error_code",
        "created_at",
    }
    rendered = str(serialized)
    for forbidden in (
        "recipient_external_id",
        "provider_message_ids",
        "last_error",
        "private-recipient",
        "provider-secret-id",
        "raw-secret",
        "Private attempt message",
    ):
        assert forbidden not in rendered


async def test_disconnected_delivery_attempt_history_remains_visible(attempt_history_case) -> None:
    session, principal, ids = attempt_history_case

    attempts = await list_channel_delivery_attempts(
        ids["disconnected_id"],
        principal,
        session,
        limit=100,
    )

    assert len(attempts) == 1
    assert attempts[0].phase == "dispatch"
    assert attempts[0].attempt_number == 8
    assert attempts[0].error_code == "broker_publish_failed"


@pytest.mark.parametrize("key", ["malformed_id", "other_delivery_id"])
async def test_attempt_history_cannot_cross_workspace_connection_boundary(
    attempt_history_case,
    key: str,
) -> None:
    session, principal, ids = attempt_history_case

    with pytest.raises(HTTPException) as exc_info:
        await list_channel_delivery_attempts(ids[key], principal, session, limit=100)
    assert exc_info.value.status_code == 404


async def test_attempt_history_requires_active_workspace(attempt_history_case) -> None:
    session, principal, ids = attempt_history_case
    no_workspace = Principal(
        user_id=principal.user_id,
        tenant_id=principal.tenant_id,
        role=principal.role,
        token_id="channel-attempt-no-workspace",
        workspace_id=None,
        workspace_role=None,
        permissions=principal.permissions,
    )

    with pytest.raises(HTTPException) as exc_info:
        await list_channel_delivery_attempts(ids["delivery_id"], no_workspace, session, limit=100)
    assert exc_info.value.status_code == 403


async def _dispatch_attempts(session: AsyncSession, delivery_id: object) -> list[ChannelDeliveryAttempt]:
    return list(
        await session.scalars(
            select(ChannelDeliveryAttempt)
            .where(
                ChannelDeliveryAttempt.delivery_id == delivery_id,
                ChannelDeliveryAttempt.phase == "dispatch",
            )
            .order_by(ChannelDeliveryAttempt.created_at, ChannelDeliveryAttempt.id)
        )
    )


async def test_dispatch_transition_history_preserves_requeue_cycles(attempt_history_case) -> None:
    session, principal, ids = attempt_history_case
    delivery = await session.get(ChannelOutboundDelivery, ids["delivery_id"])
    assert delivery is not None

    delivery.dispatch_attempts = 1
    delivery.status = "failed"
    delivery.last_error = "raw broker exception must not be copied"
    await session.commit()
    after_failure = await _dispatch_attempts(session, delivery.id)
    assert len(after_failure) == 2
    assert after_failure[-1].outcome == "publish_failed"
    assert after_failure[-1].error_code == "broker_publish_failed"

    delivery.dispatch_attempts = 0
    delivery.status = "queued"
    delivery.last_error = None
    await session.commit()
    after_reset = await _dispatch_attempts(session, delivery.id)
    assert len(after_reset) == 2  # Feature 25 counter reset is not an attempt.

    delivery.dispatch_attempts = 1
    delivery.status = "queued"
    await session.commit()

    repeated = [
        attempt
        for attempt in await _dispatch_attempts(session, delivery.id)
        if attempt.attempt_number == 1
    ]
    assert len(repeated) == 3  # seeded evidence + failed cycle + published recovery cycle
    assert [attempt.outcome for attempt in repeated].count("publish_failed") == 1
    assert [attempt.outcome for attempt in repeated].count("published") == 2
    assert all(attempt.workspace_id == principal.workspace_id for attempt in repeated)
    assert "raw broker exception" not in str([attempt.__dict__ for attempt in repeated])


async def test_provider_processing_transition_records_safe_final_outcomes(attempt_history_case) -> None:
    session, principal, ids = attempt_history_case
    delivery = await session.get(ChannelOutboundDelivery, ids["delivery_id"])
    assert delivery is not None

    delivery.status = "processing"
    delivery.attempt_count = 3
    await session.commit()

    attempts_during_processing = list(
        await session.scalars(
            select(ChannelDeliveryAttempt).where(
                ChannelDeliveryAttempt.delivery_id == delivery.id,
                ChannelDeliveryAttempt.phase == "provider",
                ChannelDeliveryAttempt.attempt_number == 3,
            )
        )
    )
    assert attempts_during_processing == []

    delivery.status = "failed"
    delivery.last_error = "Bearer raw-provider-secret must never be copied"
    await session.commit()

    delivery.status = "processing"
    delivery.attempt_count = 4
    delivery.last_error = None
    await session.commit()
    delivery.status = "sent"
    await session.commit()

    captured = list(
        await session.scalars(
            select(ChannelDeliveryAttempt)
            .where(
                ChannelDeliveryAttempt.delivery_id == delivery.id,
                ChannelDeliveryAttempt.phase == "provider",
                ChannelDeliveryAttempt.attempt_number.in_([3, 4]),
            )
            .order_by(ChannelDeliveryAttempt.attempt_number)
        )
    )
    assert [(attempt.attempt_number, attempt.outcome, attempt.error_code) for attempt in captured] == [
        (3, "failed", "provider_retryable"),
        (4, "sent", None),
    ]
    assert "raw-provider-secret" not in str([attempt.__dict__ for attempt in captured])
    assert all(attempt.workspace_id == principal.workspace_id for attempt in captured)
