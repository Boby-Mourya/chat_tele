from __future__ import annotations

from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from northstar_api.agent_purpose import AgentPurposeSetting
from northstar_api.database import SessionFactory
from northstar_api.models import OutboxEvent

pytestmark = pytest.mark.usefixtures("crm_test_plan")


async def test_agent_purpose_create_read_update_duplicate_and_safety(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    created = await client.post(
        "/api/v1/agents",
        headers=auth_headers,
        json={
            "name": "Purpose Lead Agent",
            "description": "Purpose contract test",
            "purpose": "lead_generation",
            "deploymentChannel": "website",
        },
    )
    assert created.status_code == 201, created.text
    lead_agent = created.json()
    assert lead_agent["purpose"] == "lead_generation"
    assert lead_agent["status"] == "active"
    assert "Qualify each lead" in lead_agent["instructions"]

    fetched = await client.get(f"/api/v1/agents/{lead_agent['id']}", headers=auth_headers)
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["purpose"] == "lead_generation"

    listed = await client.get("/api/v1/agents", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    listed_agent = next(item for item in listed.json() if item["id"] == lead_agent["id"])
    assert listed_agent["purpose"] == "lead_generation"

    duplicate = await client.post(
        f"/api/v1/agents/{lead_agent['id']}/duplicate",
        headers=auth_headers,
        json={"name": "Purpose Lead Agent Copy", "deploymentChannel": "api"},
    )
    assert duplicate.status_code == 201, duplicate.text
    duplicate_agent = duplicate.json()
    assert duplicate_agent["purpose"] == "lead_generation"
    assert duplicate_agent["status"] == "draft"

    education = await client.patch(
        f"/api/v1/agents/{lead_agent['id']}",
        headers=auth_headers,
        json={"purpose": "education"},
    )
    assert education.status_code == 200, education.text
    education_agent = education.json()
    assert education_agent["purpose"] == "education"
    # Education must not accidentally enter the generic live runtime before the
    # next provisioning feature installs Course/Batch/Enrollment authorization.
    assert education_agent["status"] == "draft"

    unsafe_activation = await client.patch(
        f"/api/v1/agents/{lead_agent['id']}",
        headers=auth_headers,
        json={"status": "active"},
    )
    assert unsafe_activation.status_code == 409
    assert "valid Student Enrollment" in unsafe_activation.json()["error"]["message"]

    support = await client.patch(
        f"/api/v1/agents/{lead_agent['id']}",
        headers=auth_headers,
        json={"purpose": "support"},
    )
    assert support.status_code == 200, support.text
    assert support.json()["purpose"] == "support"

    activated = await client.patch(
        f"/api/v1/agents/{lead_agent['id']}",
        headers=auth_headers,
        json={"status": "active"},
    )
    assert activated.status_code == 200, activated.text
    assert activated.json()["status"] == "active"
    assert activated.json()["purpose"] == "support"

    invalid = await client.post(
        "/api/v1/agents",
        headers=auth_headers,
        json={"name": "Invalid Purpose Agent", "purpose": "sales_magic"},
    )
    assert invalid.status_code == 422

    async with SessionFactory() as session:
        persisted = list(
            await session.scalars(
                select(AgentPurposeSetting).where(
                    AgentPurposeSetting.agent_id.in_([UUID(lead_agent["id"]), UUID(duplicate_agent["id"])])
                )
            )
        )
        assert len(persisted) == 2
        assert {item.purpose for item in persisted} == {"support", "lead_generation"}

        purpose_events = list(
            await session.scalars(
                select(OutboxEvent).where(
                    OutboxEvent.aggregate_id == lead_agent["id"],
                    OutboxEvent.event_type == "agent.purpose.changed.v1",
                )
            )
        )
        assert len(purpose_events) == 2
        transitions = {(item.payload["previousPurpose"], item.payload["purpose"]) for item in purpose_events}
        assert transitions == {
            ("lead_generation", "education"),
            ("education", "support"),
        }


async def test_legacy_lead_template_maps_to_lead_generation_purpose(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    created = await client.post(
        "/api/v1/agents",
        headers=auth_headers,
        json={
            "name": "Legacy Lead Template Agent",
            "description": "Backward compatibility",
            "template": "lead",
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["purpose"] == "lead_generation"


async def test_legacy_general_and_support_templates_keep_their_original_instructions(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    general = await client.post(
        "/api/v1/agents",
        headers=auth_headers,
        json={
            "name": "Legacy General Agent",
            "description": "No template should retain the old generic starter",
        },
    )
    assert general.status_code == 201, general.text
    general_payload = general.json()
    assert general_payload["purpose"] == "support"
    assert general_payload["instructions"].startswith("Help visitors with accurate, concise answers")

    support = await client.post(
        "/api/v1/agents",
        headers=auth_headers,
        json={
            "name": "Legacy Support Template Agent",
            "description": "Explicit support template keeps its specialist starter",
            "template": "support",
        },
    )
    assert support.status_code == 201, support.text
    support_payload = support.json()
    assert support_payload["purpose"] == "support"
    assert support_payload["instructions"].startswith("Answer customer questions using trusted knowledge")


async def test_education_agent_is_created_in_draft(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    created = await client.post(
        "/api/v1/agents",
        headers=auth_headers,
        json={
            "name": "Education Purpose Agent",
            "description": "Safe education provisioning",
            "purpose": "education",
        },
    )
    assert created.status_code == 201, created.text
    payload = created.json()
    assert payload["purpose"] == "education"
    assert payload["status"] == "draft"
    assert "authorized course knowledge" in payload["instructions"]


async def test_telegram_channel_survives_create_edit_and_duplicate(
    client: AsyncClient, auth_headers: dict[str, str],
) -> None:
    created = await client.post(
        "/api/v1/agents", headers=auth_headers,
        json={"name": "Telegram Assistant", "deploymentChannel": "telegram"},
    )
    assert created.status_code == 201, created.text
    agent = created.json()
    assert agent["appearance"]["deploymentChannel"] == "telegram"
    updated = await client.patch(
        f"/api/v1/agents/{agent['id']}", headers=auth_headers,
        json={"appearance": {**agent["appearance"], "welcomeTitle": "Telegram helper"}},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["appearance"]["deploymentChannel"] == "telegram"
    duplicate = await client.post(
        f"/api/v1/agents/{agent['id']}/duplicate", headers=auth_headers,
        json={"name": "Telegram Copy", "deploymentChannel": "telegram"},
    )
    assert duplicate.status_code == 201, duplicate.text
    assert duplicate.json()["appearance"]["deploymentChannel"] == "telegram"
    binding = await client.get(f"/api/v1/agents/{agent['id']}/channel", headers=auth_headers)
    assert binding.status_code == 200, binding.text
    assert binding.json()["channelType"] == "telegram"
