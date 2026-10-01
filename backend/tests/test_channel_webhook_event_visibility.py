from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from northstar_api.database import Base
from northstar_api.lead_crm.channel_models import ChannelConnection
from northstar_api.lead_crm.channel_scope import WorkspaceChannelConnection
from northstar_api.lead_crm.models import RawWebhookEvent
from northstar_api.models import Agent, Role, Tenant, Workspace, WorkspaceRole
from northstar_api.routers.channel_webhook_events import list_channel_webhook_events
from northstar_api.security import Principal


@pytest.fixture
async def channel_webhook_visibility_case() -> AsyncIterator[tuple[AsyncSession, Principal, dict[str, object]]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        tenant = Tenant(slug=f"channel-webhook-{uuid4().hex}", name="Channel webhook visibility")
        session.add(tenant)
        await session.flush()

        workspace = Workspace(
            tenant_id=tenant.id,
            name="Primary channel workspace",
            slug=f"primary-channel-{uuid4().hex[:8]}",
        )
        other_workspace = Workspace(
            tenant_id=tenant.id,
            name="Other channel workspace",
            slug=f"other-channel-{uuid4().hex[:8]}",
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

        telegram = ChannelConnection(
            tenant_id=tenant.id,
            provider="telegram",
            name="Primary Telegram",
            status="healthy",
            configuration_json={},
        )
        slack = ChannelConnection(
            tenant_id=tenant.id,
            provider="slack",
            name="Primary Slack",
            status="healthy",
            configuration_json={},
        )
        other_connection = ChannelConnection(
            tenant_id=tenant.id,
            provider="instagram",
            name="Other Instagram",
            status="healthy",
            configuration_json={},
        )
        session.add_all([telegram, slack, other_connection])
        await session.flush()
        session.add_all([
            WorkspaceChannelConnection(
                tenant_id=tenant.id,
                workspace_id=workspace.id,
                agent_id=agent.id,
                connection_id=telegram.id,
            ),
            WorkspaceChannelConnection(
                tenant_id=tenant.id,
                workspace_id=workspace.id,
                agent_id=agent.id,
                connection_id=slack.id,
            ),
            WorkspaceChannelConnection(
                tenant_id=tenant.id,
                workspace_id=other_workspace.id,
                agent_id=other_agent.id,
                connection_id=other_connection.id,
            ),
        ])
        await session.flush()

        now = datetime(2026, 9, 12, 13, 0, tzinfo=UTC)
        session.add_all([
            RawWebhookEvent(
                tenant_id=tenant.id,
                connection_key=str(telegram.id),
                provider="telegram",
                external_event_id="private-telegram-event-id",
                event_type="message.received",
                payload_json={
                    "message": {"text": "private student question"},
                    "bot_token": "must-not-leak",
                },
                headers_json={"authorization": "Bearer must-not-leak"},
                payload_hash="a" * 64,
                verification_status="verified",
                processing_status="processed",
                attempt_count=1,
                received_at=now - timedelta(minutes=3),
                processed_at=now - timedelta(minutes=2),
                last_error="provider response with private detail",
                correlation_id="corr-telegram-processed",
            ),
            RawWebhookEvent(
                tenant_id=tenant.id,
                connection_key=str(slack.id),
                provider="slack",
                external_event_id="private-slack-event-id",
                event_type="message.received",
                payload_json={"text": "private slack message", "secret": "also-private"},
                headers_json={"x-slack-signature": "private-signature"},
                payload_hash="b" * 64,
                verification_status="verified",
                processing_status="failed",
                attempt_count=2,
                received_at=now,
                processed_at=None,
                last_error="credential decoding detail must never be returned",
                correlation_id="corr-slack-failed",
            ),
            RawWebhookEvent(
                tenant_id=tenant.id,
                connection_key=str(other_connection.id),
                provider="instagram",
                external_event_id="other-workspace-event",
                event_type="message.received",
                payload_json={"secret": "other-workspace-secret"},
                headers_json={"authorization": "other-workspace-auth"},
                payload_hash="c" * 64,
                verification_status="verified",
                processing_status="rejected",
                attempt_count=1,
                received_at=now + timedelta(minutes=1),
                processed_at=now + timedelta(minutes=1),
                last_error="other workspace private error",
                correlation_id="corr-other-workspace",
            ),
        ])
        await session.commit()

        principal = Principal(
            user_id=uuid4(),
            tenant_id=tenant.id,
            role=Role.MEMBER,
            token_id="channel-webhook-visibility",
            workspace_id=workspace.id,
            workspace_role=WorkspaceRole.MANAGER,
            permissions=frozenset({"integrations.view"}),
        )
        yield session, principal, {
            "telegram_id": telegram.id,
            "slack_id": slack.id,
            "other_connection_id": other_connection.id,
        }

    await engine.dispose()


async def test_channel_webhook_events_are_workspace_scoped_and_secret_safe(
    channel_webhook_visibility_case,
) -> None:
    session, principal, _ = channel_webhook_visibility_case

    rows = await list_channel_webhook_events(
        principal,
        session,
        connection_id=None,
        processing_status=None,
        provider=None,
        limit=100,
    )

    assert [row.correlation_id for row in rows] == [
        "corr-slack-failed",
        "corr-telegram-processed",
    ]
    assert rows[0].error_code == "processing_failed"
    assert rows[1].error_code is None
    rendered = str([row.model_dump(mode="json") for row in rows])
    for forbidden in (
        "payload_json",
        "headers_json",
        "payload_hash",
        "external_event_id",
        "last_error",
        "private student question",
        "private slack message",
        "must-not-leak",
        "private-signature",
        "credential decoding detail",
        "other-workspace",
    ):
        assert forbidden not in rendered


async def test_channel_webhook_events_filter_owned_connection_status_and_provider(
    channel_webhook_visibility_case,
) -> None:
    session, principal, ids = channel_webhook_visibility_case

    rows = await list_channel_webhook_events(
        principal,
        session,
        connection_id=ids["slack_id"],
        processing_status="failed",
        provider="slack",
        limit=20,
    )

    assert len(rows) == 1
    assert rows[0].connection_id == ids["slack_id"]
    assert rows[0].processing_status == "failed"
    assert rows[0].provider == "slack"
    assert rows[0].attempt_count == 2
    assert rows[0].error_code == "processing_failed"


async def test_channel_webhook_events_reject_connection_from_another_workspace(
    channel_webhook_visibility_case,
) -> None:
    session, principal, ids = channel_webhook_visibility_case

    with pytest.raises(HTTPException) as exc_info:
        await list_channel_webhook_events(
            principal,
            session,
            connection_id=ids["other_connection_id"],
            processing_status=None,
            provider=None,
            limit=20,
        )
    assert exc_info.value.status_code == 404


async def test_channel_webhook_events_require_active_workspace(channel_webhook_visibility_case) -> None:
    session, principal, _ = channel_webhook_visibility_case
    no_workspace = Principal(
        user_id=principal.user_id,
        tenant_id=principal.tenant_id,
        role=principal.role,
        token_id="channel-webhook-no-workspace",
        workspace_id=None,
        workspace_role=None,
        permissions=principal.permissions,
    )

    with pytest.raises(HTTPException) as exc_info:
        await list_channel_webhook_events(
            no_workspace,
            session,
            connection_id=None,
            processing_status=None,
            provider=None,
            limit=20,
        )
    assert exc_info.value.status_code == 403
