from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from test_education_channel_runtime import _seed_authorized_student

from northstar_api.database import SessionFactory
from northstar_api.models import Agent, IntegrationConnection, WhatsAppConnection

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("crm_test_plan")]


async def create_bot(client, headers, channel="whatsapp"):
    response = await client.post(
        "/api/v1/agents",
        headers=headers,
        json={"name": f"Deployment audit {uuid4().hex[:8]}", "deploymentChannel": channel},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def add_number(agent_id, display="+15550199999"):
    async with SessionFactory() as session:
        agent = await session.get(Agent, UUID(agent_id))
        number = WhatsAppConnection(
            tenant_id=agent.tenant_id,
            workspace_id=agent.workspace_id,
            waba_id="deploy-test",
            phone_number_id=uuid4().hex,
            display_phone_number=display,
            verified_name="Deployment test",
            status="connected",
            access_token_encrypted=b"test",
        )
        session.add(number)
        await session.commit()
        return str(number.id)


async def test_draft_can_be_assigned_then_activated_and_inactivated(client, auth_headers):
    bot = await create_bot(client, auth_headers)
    agent_url = f"/api/v1/agents/{bot['id']}"
    assert bot["status"] == "draft"
    assert (await client.patch(agent_url, headers=auth_headers, json={"status": "active"})).status_code == 409
    number_id = await add_number(bot["id"])
    assignment_url = f"/api/v1/integrations/whatsapp-accounts/numbers/{number_id}/assignment"
    assigned = await client.put(assignment_url, headers=auth_headers, json={"agentId": bot["id"]})
    assert assigned.status_code == 200, assigned.text
    saved = (await client.get(agent_url, headers=auth_headers)).json()
    assert saved["status"] == "draft" and saved["whatsappNumber"] == "+15550199999"
    activated = await client.patch(agent_url, headers=auth_headers, json={"status": "active"})
    assert activated.status_code == 200, activated.text
    assert activated.json()["status"] == "active"
    assert (await client.patch(agent_url, headers=auth_headers, json={"status": "draft"})).status_code == 200
    async with SessionFactory() as session:
        number = await session.get(WhatsAppConnection, UUID(number_id))
        number.token_expires_at = datetime.now(UTC) - timedelta(hours=1)
        await session.commit()
    assert (await client.patch(agent_url, headers=auth_headers, json={"status": "active"})).status_code == 409
    released = await client.put(assignment_url, headers=auth_headers, json={"agentId": None})
    assert released.status_code == 200, released.text
    assert (await client.get(agent_url, headers=auth_headers)).json()["whatsappNumber"] is None


async def test_changing_channel_cannot_bypass_number_requirement(client, auth_headers):
    bot = await create_bot(client, auth_headers, "website")
    assert bot["status"] == "active"
    url = f"/api/v1/agents/{bot['id']}"
    appearance = {**bot["appearance"], "deploymentChannel": "whatsapp"}
    for payload in [{"appearance": appearance}, {"appearance": appearance, "status": "active"}]:
        response = await client.patch(url, headers=auth_headers, json=payload)
        assert response.status_code == 409, response.text
    updated = await client.patch(
        url, headers=auth_headers, json={"appearance": appearance, "status": "draft"}
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["status"] == "draft"


async def test_saving_education_settings_preserves_activation(client, auth_headers):
    seeded, headers = await _seed_authorized_student(client, auth_headers)
    url = f"/api/v1/agents/{seeded['agentId']}"
    bot = (await client.get(url, headers=headers)).json()
    assert bot["status"] == "active"
    updated = await client.patch(
        url,
        headers=headers,
        json={
            "purpose": "education",
            "appearance": {
                **bot["appearance"],
                "whatsapp": {"welcomeMessage": "*Welcome!*", "replyTemplate": "{message}"},
            },
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["status"] == "active"
    assert updated.json()["appearance"]["whatsapp"]["welcomeMessage"] == "*Welcome!*"


async def test_number_transfer_and_release_preserve_connected_inventory(client, auth_headers):
    first = await create_bot(client, auth_headers)
    second = await create_bot(client, auth_headers)
    number_id = await add_number(first["id"])
    async with SessionFactory() as session:
        agent = await session.get(Agent, UUID(first["id"]))
        integration = await session.scalar(
            select(IntegrationConnection).where(
                IntegrationConnection.tenant_id == agent.tenant_id,
                IntegrationConnection.workspace_id == agent.workspace_id,
                IntegrationConnection.integration_id == "whatsapp",
            )
        )
        if not integration:
            integration = IntegrationConnection(
                tenant_id=agent.tenant_id,
                workspace_id=agent.workspace_id,
                integration_id="whatsapp",
                connected=True,
            )
            session.add(integration)
        integration.connected = True
        await session.commit()
        integration_id = integration.id
    url = f"/api/v1/integrations/whatsapp-accounts/numbers/{number_id}/assignment"
    for bot in [first, second]:
        response = await client.put(url, headers=auth_headers, json={"agentId": bot["id"]})
        assert response.status_code == 200, response.text
    assert (await client.get(f"/api/v1/agents/{first['id']}", headers=auth_headers)).json()[
        "whatsappNumber"
    ] is None
    assert (await client.get(f"/api/v1/agents/{second['id']}", headers=auth_headers)).json()[
        "whatsappNumber"
    ] == "+15550199999"
    assert (await client.put(url, headers=auth_headers, json={"agentId": None})).status_code == 200
    async with SessionFactory() as session:
        number = await session.get(WhatsAppConnection, UUID(number_id))
        assert number.agent_id is None and number.status == "connected"
        assert (await session.get(IntegrationConnection, integration_id)).connected


async def test_meta_phone_id_is_never_presented_as_a_customer_phone_number(client, auth_headers):
    bot = await create_bot(client, auth_headers)
    number_id = await add_number(bot["id"], "")
    async with SessionFactory() as session:
        number = await session.get(WhatsAppConnection, UUID(number_id))
        number.phone_number_id = "123456789012345"
        number.agent_id = UUID(bot["id"])
        await session.commit()
    assert (await client.get(f"/api/v1/agents/{bot['id']}", headers=auth_headers)).json()[
        "whatsappNumber"
    ] is None
