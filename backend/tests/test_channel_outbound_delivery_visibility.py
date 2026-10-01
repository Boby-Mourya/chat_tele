from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from northstar_api.database import Base
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
    Workspace,
    WorkspaceRole,
)
from northstar_api.routers.channel_deliveries import list_channel_deliveries
from northstar_api.security import Principal


@pytest.fixture
async def delivery_visibility_case() -> AsyncIterator[tuple[AsyncSession, Principal, dict[str, object]]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        tenant = Tenant(slug=f"delivery-visibility-{uuid4().hex}", name="Delivery visibility")
        session.add(tenant)
        await session.flush()

        workspace = Workspace(
            tenant_id=tenant.id,
            name="Primary workspace",
            slug=f"primary-delivery-{uuid4().hex[:8]}",
        )
        other_workspace = Workspace(
            tenant_id=tenant.id,
            name="Other workspace",
            slug=f"other-delivery-{uuid4().hex[:8]}",
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

        primary_messages = [
            Message(
                tenant_id=tenant.id,
                workspace_id=workspace.id,
                conversation_id=conversation.id,
                sequence=index,
                role=MessageRole.ASSISTANT,
                content=f"Private primary message {index}",
            )
            for index in range(1, 4)
        ]
        other_message = Message(
            tenant_id=tenant.id,
            workspace_id=other_workspace.id,
            conversation_id=other_conversation.id,
            sequence=1,
            role=MessageRole.ASSISTANT,
            content="Other workspace message must not leak",
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
            status="healthy",
            configuration_json={},
        )
        session.add_all([primary_connection, other_connection])
        await session.flush()
        session.add_all([
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
        ])
        await session.flush()

        visible = ChannelOutboundDelivery(
            tenant_id=tenant.id,
            workspace_id=workspace.id,
            connection_id=primary_connection.id,
            message_id=primary_messages[0].id,
            provider="telegram",
            recipient_external_id="private-recipient-42",
            status="failed",
            attempt_count=2,
            dispatch_attempts=3,
            provider_message_ids=["provider-secret-id"],
            last_error="Bearer secret-token provider response body",
        )
        disconnected = ChannelOutboundDelivery(
            tenant_id=tenant.id,
            workspace_id=workspace.id,
            connection_id=None,
            message_id=primary_messages[1].id,
            provider="telegram",
            recipient_external_id="private-recipient-43",
            status="reconnect_required",
            last_error="Raw authorization response must never be returned",
        )
        other_delivery = ChannelOutboundDelivery(
            tenant_id=tenant.id,
            workspace_id=other_workspace.id,
            connection_id=other_connection.id,
            message_id=other_message.id,
            provider="slack",
            recipient_external_id="C999|1.0",
            status="dispatch_failed",
            last_error="Other workspace failure must not leak",
        )
        malformed_cross_workspace_connection = ChannelOutboundDelivery(
            tenant_id=tenant.id,
            workspace_id=workspace.id,
            connection_id=other_connection.id,
            message_id=primary_messages[2].id,
            provider="slack",
            recipient_external_id="other-private-recipient",
            status="rejected",
            last_error="Connection binding must prevent this row from leaking",
        )
        session.add_all([
            visible,
            disconnected,
            other_delivery,
            malformed_cross_workspace_connection,
        ])
        await session.commit()

        principal = Principal(
            user_id=uuid4(),
            tenant_id=tenant.id,
            role=Role.MEMBER,
            token_id="channel-delivery-visibility",
            workspace_id=workspace.id,
            workspace_role=WorkspaceRole.MANAGER,
            permissions=frozenset({"integrations.view"}),
        )
        yield session, principal, {
            "connection_id": primary_connection.id,
            "visible_id": visible.id,
            "disconnected_id": disconnected.id,
        }

    await engine.dispose()


async def test_channel_deliveries_are_workspace_scoped_and_safe(delivery_visibility_case) -> None:
    session, principal, ids = delivery_visibility_case

    result = await list_channel_deliveries(
        principal,
        session,
        connection_id=None,
        status=None,
        limit=100,
    )

    assert {row.id for row in result} == {ids["visible_id"], ids["disconnected_id"]}
    visible = next(row for row in result if row.id == ids["visible_id"])
    assert visible.connection_name == "Primary Telegram"
    assert visible.status == "failed"
    assert visible.error_code == "retryable_failure"
    assert visible.attempt_count == 2
    assert visible.dispatch_attempts == 3

    serialized = [row.model_dump(mode="json") for row in result]
    rendered = str(serialized)
    for forbidden in (
        "recipient_external_id",
        "provider_message_ids",
        "last_error",
        "Private primary message",
        "secret-token",
        "provider-secret-id",
        "private-recipient",
        "Other workspace",
    ):
        assert forbidden not in rendered


async def test_channel_deliveries_support_owned_connection_and_status_filters(
    delivery_visibility_case,
) -> None:
    session, principal, ids = delivery_visibility_case

    result = await list_channel_deliveries(
        principal,
        session,
        connection_id=ids["connection_id"],
        status="failed",
        limit=25,
    )

    assert len(result) == 1
    assert result[0].id == ids["visible_id"]
    assert result[0].error_code == "retryable_failure"


async def test_channel_deliveries_reject_connection_from_another_workspace(
    delivery_visibility_case,
) -> None:
    session, principal, _ = delivery_visibility_case
    other_connection = ChannelConnection(
        tenant_id=principal.tenant_id,
        provider="custom",
        name=f"Unscoped {uuid4().hex[:8]}",
        configuration_json={},
    )
    session.add(other_connection)
    await session.commit()

    with pytest.raises(HTTPException) as exc_info:
        await list_channel_deliveries(
            principal,
            session,
            connection_id=other_connection.id,
            status=None,
            limit=10,
        )
    assert exc_info.value.status_code == 404


async def test_channel_deliveries_require_active_workspace(delivery_visibility_case) -> None:
    session, principal, _ = delivery_visibility_case
    no_workspace = Principal(
        user_id=principal.user_id,
        tenant_id=principal.tenant_id,
        role=principal.role,
        token_id="channel-delivery-no-workspace",
        workspace_id=None,
        workspace_role=None,
        permissions=principal.permissions,
    )

    with pytest.raises(HTTPException) as exc_info:
        await list_channel_deliveries(
            no_workspace,
            session,
            connection_id=None,
            status=None,
            limit=10,
        )
    assert exc_info.value.status_code == 403
