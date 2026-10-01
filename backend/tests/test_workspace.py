from __future__ import annotations

from httpx import AsyncClient


async def test_workspace_profile_and_white_label_are_tenant_scoped(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    current = await client.get("/api/v1/workspace", headers=auth_headers)
    assert current.status_code == 200, current.text
    original = current.json()
    assert original["id"]
    assert original["memberCount"] >= 1

    branding = {
        **original["whiteLabel"],
        "companyName": "Example Support",
        "primaryColor": "#123456",
        "secondaryColor": "#654321",
        "customDomain": "chat.example.com",
        "dnsStatus": "pending",
        "removePlatformBranding": True,
    }
    updated = await client.patch(
        "/api/v1/workspace",
        headers=auth_headers,
        json={"whiteLabel": branding},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["whiteLabel"]["companyName"] == "Example Support"
    assert updated.json()["whiteLabel"]["customDomain"] == "chat.example.com"

    invalid = await client.patch(
        "/api/v1/workspace",
        headers=auth_headers,
        json={"whiteLabel": {**branding, "primaryColor": "blue"}},
    )
    assert invalid.status_code == 422

    restored = await client.patch(
        "/api/v1/workspace",
        headers=auth_headers,
        json={"name": original["name"], "slug": original["slug"], "whiteLabel": original["whiteLabel"]},
    )
    assert restored.status_code == 200, restored.text


async def test_selected_workspace_isolates_agents_and_rejects_unknown_membership(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    original_response = await client.get("/api/v1/workspace", headers=auth_headers)
    assert original_response.status_code == 200, original_response.text
    original_id = original_response.json()["id"]

    created_workspace = await client.post(
        "/api/v1/workspaces",
        headers=auth_headers,
        json={"name": "Workspace Isolation Test", "slug": "workspace-isolation-test"},
    )
    assert created_workspace.status_code in {201, 409}, created_workspace.text
    if created_workspace.status_code == 201:
        secondary_id = created_workspace.json()["id"]
    else:
        workspaces = await client.get("/api/v1/workspaces", headers=auth_headers)
        secondary_id = next(
            item["id"] for item in workspaces.json() if item["slug"] == "workspace-isolation-test"
        )

    secondary_headers = {**auth_headers, "X-Workspace-ID": secondary_id}
    created_agent = await client.post(
        "/api/v1/agents",
        headers=secondary_headers,
        json={"name": "Secondary Workspace Agent", "description": "Isolation fixture"},
    )
    assert created_agent.status_code in {201, 409}, created_agent.text

    secondary_agents = await client.get("/api/v1/agents", headers=secondary_headers)
    assert secondary_agents.status_code == 200, secondary_agents.text
    assert any(item["name"] == "Secondary Workspace Agent" for item in secondary_agents.json())
    assert all(item["workspaceId"] == secondary_id for item in secondary_agents.json())

    original_agents = await client.get(
        "/api/v1/agents",
        headers={**auth_headers, "X-Workspace-ID": original_id},
    )
    assert original_agents.status_code == 200, original_agents.text
    assert all(item["name"] != "Secondary Workspace Agent" for item in original_agents.json())
    assert all(item["workspaceId"] == original_id for item in original_agents.json())

    unavailable = await client.get(
        "/api/v1/agents",
        headers={**auth_headers, "X-Workspace-ID": "00000000-0000-0000-0000-000000000000"},
    )
    assert unavailable.status_code == 403
