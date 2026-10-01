from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from northstar_api.database import SessionFactory
from northstar_api.models import Agent, Channel, Conversation, ConversationState, Lead


@pytest.mark.usefixtures("crm_test_plan")
async def test_sales_intent_rejected_even_without_education_context(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    workspace = await client.get("/api/v1/workspace", headers=auth_headers)
    assert workspace.status_code == 200, workspace.text
    workspace_id = workspace.json()["id"]
    headers = {**auth_headers, "X-Workspace-ID": workspace_id}
    seed = uuid.uuid4().hex[:8]

    enabled = await client.patch(
        "/api/v1/education/settings/sales-routing",
        headers=headers,
        json={"createUpsellLeads": True},
    )
    assert enabled.status_code == 409, enabled.text

    created_agent = await client.post(
        "/api/v1/agents",
        headers=headers,
        json={
            "name": f"Upsell Context Guard {seed}",
            "description": "Requires an immutable Education conversation context",
            "purpose": "education",
            "deploymentChannel": "website",
        },
    )
    assert created_agent.status_code == 201, created_agent.text

    async with SessionFactory() as session:
        agent = await session.scalar(
            select(Agent).where(Agent.id == uuid.UUID(created_agent.json()["id"]))
        )
        assert agent is not None
        conversation = Conversation(
            tenant_id=agent.tenant_id,
            workspace_id=agent.workspace_id,
            agent_id=agent.id,
            visitor_id=f"upsell-context-guard-{seed}",
            visitor_name="Education Student",
            visitor_email=f"upsell-context-{seed}@example.com",
            channel=Channel.WIDGET,
        )
        session.add(conversation)
        await session.flush()
        conversation_id = conversation.id
        await session.commit()

    response = await client.post(
        f"/api/v1/education/conversations/{conversation_id}/resolve-sales-intent",
        headers=headers,
    )
    assert response.status_code == 409, response.text
    assert "Education chats stay in Conversations" in response.json()["error"]["message"]

    async with SessionFactory() as session:
        persisted = await session.get(Conversation, conversation_id)
        assert persisted is not None
        assert persisted.state == ConversationState.OPEN
        leads = list(
            await session.scalars(select(Lead).where(Lead.conversation_id == conversation_id))
        )
        assert leads == []
