from __future__ import annotations

from uuid import UUID, uuid4

from httpx import AsyncClient

from northstar_api.database import SessionFactory
from northstar_api.security import token_fingerprint
from northstar_api.workspace_api_keys import WorkspaceAPIKey


async def test_workspace_api_key_is_hashed_scoped_usable_and_revocable(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    workspace_response = await client.get("/api/v1/workspace", headers=auth_headers)
    assert workspace_response.status_code == 200, workspace_response.text
    workspace_id = workspace_response.json()["id"]

    secondary = await client.post(
        "/api/v1/workspaces",
        headers=auth_headers,
        json={
            "name": "API Key Isolation Workspace",
            "slug": f"api-key-isolation-{uuid4().hex[:10]}",
        },
    )
    assert secondary.status_code == 201, secondary.text
    secondary_workspace_id = secondary.json()["id"]

    created = await client.post(
        "/api/v1/workspace/api-keys",
        headers=auth_headers,
        json={"name": "  Production   Integration  "},
    )
    assert created.status_code == 201, created.text
    payload = created.json()
    assert payload["name"] == "Production Integration"
    assert payload["secret"].startswith("nsk_live_")
    assert payload["prefix"] == payload["secret"][:16]
    api_key_id = UUID(payload["id"])
    secret = payload["secret"]

    async with SessionFactory() as session:
        stored = await session.get(WorkspaceAPIKey, api_key_id)
        assert stored is not None
        assert stored.secret_hash == token_fingerprint(secret)
        assert stored.secret_hash != secret
        assert not hasattr(stored, "secret")
        assert str(stored.workspace_id) == workspace_id

    listed = await client.get("/api/v1/workspace/api-keys", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    listed_key = next(item for item in listed.json() if item["id"] == payload["id"])
    assert listed_key["name"] == "Production Integration"
    assert listed_key["prefix"] == payload["prefix"]
    assert "secret" not in listed_key

    api_headers = {"Authorization": f"Bearer {secret}"}
    api_workspace = await client.get("/api/v1/workspace", headers=api_headers)
    assert api_workspace.status_code == 200, api_workspace.text
    assert api_workspace.json()["id"] == workspace_id

    visible_workspaces = await client.get("/api/v1/workspaces", headers=api_headers)
    assert visible_workspaces.status_code == 200, visible_workspaces.text
    assert [item["id"] for item in visible_workspaces.json()] == [workspace_id]

    explicit_other_workspace = await client.get(
        f"/api/v1/workspaces/{secondary_workspace_id}",
        headers=api_headers,
    )
    assert explicit_other_workspace.status_code == 403, explicit_other_workspace.text

    mismatched_workspace = await client.get(
        "/api/v1/workspace",
        headers={**api_headers, "X-Workspace-ID": str(uuid4())},
    )
    assert mismatched_workspace.status_code == 403, mismatched_workspace.text
    assert "different workspace" in mismatched_workspace.json()["error"]["message"].lower()

    refreshed_list = await client.get("/api/v1/workspace/api-keys", headers=auth_headers)
    refreshed_key = next(item for item in refreshed_list.json() if item["id"] == payload["id"])
    assert refreshed_key["lastUsedAt"] is not None

    revoked = await client.delete(
        f"/api/v1/workspace/api-keys/{payload['id']}",
        headers=auth_headers,
    )
    assert revoked.status_code == 204, revoked.text

    rejected = await client.get("/api/v1/workspace", headers=api_headers)
    assert rejected.status_code == 401, rejected.text
    assert rejected.json()["error"]["message"] == "Invalid or revoked API key"

    after = await client.get("/api/v1/workspace/api-keys", headers=auth_headers)
    assert after.status_code == 200, after.text
    assert all(item["id"] != payload["id"] for item in after.json())


async def test_workspace_api_key_cannot_manage_api_keys(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    created = await client.post(
        "/api/v1/workspace/api-keys",
        headers=auth_headers,
        json={"name": "Runtime Key"},
    )
    assert created.status_code == 201, created.text
    secret = created.json()["secret"]

    attempted = await client.post(
        "/api/v1/workspace/api-keys",
        headers={"Authorization": f"Bearer {secret}"},
        json={"name": "Child Key"},
    )
    assert attempted.status_code == 403, attempted.text
