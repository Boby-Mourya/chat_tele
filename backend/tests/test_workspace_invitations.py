from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy import select

from northstar_api.database import SessionFactory
from northstar_api.routers import workspace, workspace_invitations
from northstar_api.workspace_invitations import WorkspaceInvitation


def test_workspace_invitation_create_route_is_registered_once() -> None:
    matches = [
        route
        for route in [*workspace.router.routes, *workspace_invitations.router.routes]
        if getattr(route, "path", None) == "/workspace/invitations"
        and "POST" in getattr(route, "methods", set())
    ]
    assert len(matches) == 1


async def _workspace_id(client: AsyncClient, auth_headers: dict[str, str]) -> str:
    response = await client.get("/api/v1/workspace", headers=auth_headers)
    assert response.status_code == 200, response.text
    return response.json()["id"]


async def test_invited_signup_creates_restricted_membership_and_member_lifecycle(
    client: AsyncClient,
    auth_headers: dict[str, str],
    monkeypatch,
) -> None:
    delivered_tokens: list[str] = []

    async def capture_invitation(**kwargs) -> None:
        delivered_tokens.append(kwargs["raw_token"])

    monkeypatch.setattr(
        "northstar_api.routers.workspace_invitations.send_workspace_invitation_email",
        capture_invitation,
    )
    workspace_id = await _workspace_id(client, auth_headers)
    scoped_headers = {**auth_headers, "X-Workspace-ID": workspace_id}
    agent_response = await client.post(
        "/api/v1/agents",
        headers=scoped_headers,
        json={
            "name": "Invitation Restricted Agent",
            "description": "Membership scope fixture",
        },
    )
    assert agent_response.status_code in {201, 409}, agent_response.text
    if agent_response.status_code == 201:
        agent_id = agent_response.json()["id"]
    else:
        agents = await client.get("/api/v1/agents", headers=scoped_headers)
        agent_id = next(
            item["id"]
            for item in agents.json()
            if item["name"] == "Invitation Restricted Agent"
        )

    invited_email = "restricted-invitee@example.com"
    created = await client.post(
        "/api/v1/workspace/invitations",
        headers=scoped_headers,
        json={
            "email": invited_email,
            "role": "operator",
            "allAgentsAccess": False,
            "agentIds": [agent_id],
        },
    )
    assert created.status_code == 201, created.text
    invitation = created.json()
    assert invitation["status"] == "pending"
    assert invitation["agentIds"] == [agent_id]
    assert invitation["deliveryState"] == "sent"
    assert "token" not in invitation
    assert len(delivered_tokens) == 1
    raw_token = delivered_tokens[0]

    async with SessionFactory() as session:
        stored = await session.scalar(
            select(WorkspaceInvitation).where(WorkspaceInvitation.email == invited_email)
        )
        assert stored is not None
        assert stored.token_hash != raw_token
        assert len(stored.token_hash) == 64

    preview = await client.post(
        "/api/v1/workspace-invitations/preview",
        json={"token": raw_token},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["workspaceId"] == workspace_id
    assert preview.json()["existingUser"] is False
    assert preview.json()["agentCount"] == 1

    signed_up = await client.post(
        "/api/v1/workspace-invitations/signup",
        json={
            "token": raw_token,
            "name": "Restricted Invitee",
            "password": "Restricted-Invitee-Password-42!",
            "termsAccepted": True,
            "privacyAccepted": True,
        },
    )
    assert signed_up.status_code == 201, signed_up.text
    invited_session = signed_up.json()
    assert invited_session["workspaceId"] == workspace_id
    assert invited_session["user"]["email"] == invited_email
    assert invited_session["user"]["emailVerified"] is True
    invited_headers = {
        "Authorization": f"Bearer {invited_session['accessToken']}",
        "X-Workspace-ID": workspace_id,
    }

    replay = await client.post(
        "/api/v1/workspace-invitations/signup",
        json={
            "token": raw_token,
            "name": "Replay",
            "password": "Replay-Invitation-Password-42!",
            "termsAccepted": True,
            "privacyAccepted": True,
        },
    )
    assert replay.status_code == 404

    visible_agents = await client.get("/api/v1/agents", headers=invited_headers)
    assert visible_agents.status_code == 200, visible_agents.text
    assert [item["id"] for item in visible_agents.json()] == [agent_id]
    assert (await client.get("/api/v1/workspace/members", headers=invited_headers)).status_code == 403

    members = await client.get("/api/v1/workspace/members", headers=scoped_headers)
    assert members.status_code == 200, members.text
    invited_member = next(item for item in members.json() if item["email"] == invited_email)
    assert invited_member["role"] == "operator"
    assert invited_member["allAgentsAccess"] is False
    assert invited_member["agentIds"] == [agent_id]

    updated = await client.patch(
        f"/api/v1/workspace/members/{invited_member['userId']}",
        headers=scoped_headers,
        json={"role": "manager", "allAgentsAccess": True, "agentIds": []},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["role"] == "manager"
    assert updated.json()["allAgentsAccess"] is True
    assert (await client.get("/api/v1/workspace/members", headers=invited_headers)).status_code == 200

    self_change = await client.patch(
        f"/api/v1/workspace/members/{invited_member['userId']}",
        headers=invited_headers,
        json={"role": "viewer", "allAgentsAccess": True, "agentIds": []},
    )
    assert self_change.status_code == 403

    removed = await client.delete(
        f"/api/v1/workspace/members/{invited_member['userId']}",
        headers=scoped_headers,
    )
    assert removed.status_code == 204, removed.text
    assert (await client.get("/api/v1/workspace", headers=invited_headers)).status_code in {401, 403}


async def test_invitation_resend_decline_revoke_and_self_protection(
    client: AsyncClient,
    auth_headers: dict[str, str],
    monkeypatch,
) -> None:
    delivered_tokens: list[str] = []

    async def capture_invitation(**kwargs) -> None:
        delivered_tokens.append(kwargs["raw_token"])

    monkeypatch.setattr(
        "northstar_api.routers.workspace_invitations.send_workspace_invitation_email",
        capture_invitation,
    )
    workspace_id = await _workspace_id(client, auth_headers)
    scoped_headers = {**auth_headers, "X-Workspace-ID": workspace_id}
    created = await client.post(
        "/api/v1/workspace/invitations",
        headers=scoped_headers,
        json={
            "email": "resend-decline@example.com",
            "role": "analyst",
            "allAgentsAccess": True,
            "agentIds": [],
        },
    )
    assert created.status_code == 201, created.text
    invitation_id = created.json()["id"]
    original_token = delivered_tokens[-1]

    resent = await client.post(
        f"/api/v1/workspace/invitations/{invitation_id}/resend",
        headers=scoped_headers,
    )
    assert resent.status_code == 200, resent.text
    assert resent.json()["deliveryAttempts"] == 2
    rotated_token = delivered_tokens[-1]
    assert rotated_token != original_token
    old_preview = await client.post(
        "/api/v1/workspace-invitations/preview",
        json={"token": original_token},
    )
    assert old_preview.status_code == 404

    declined = await client.post(
        "/api/v1/workspace-invitations/decline",
        json={"token": rotated_token},
    )
    assert declined.status_code == 200, declined.text
    cannot_resend = await client.post(
        f"/api/v1/workspace/invitations/{invitation_id}/resend",
        headers=scoped_headers,
    )
    assert cannot_resend.status_code == 409

    reissued = await client.post(
        "/api/v1/workspace/invitations",
        headers=scoped_headers,
        json={
            "email": "resend-decline@example.com",
            "role": "viewer",
            "allAgentsAccess": True,
            "agentIds": [],
        },
    )
    assert reissued.status_code == 201, reissued.text
    assert reissued.json()["id"] == invitation_id
    active_token = delivered_tokens[-1]
    revoked = await client.delete(
        f"/api/v1/workspace/invitations/{invitation_id}",
        headers=scoped_headers,
    )
    assert revoked.status_code == 204, revoked.text
    revoked_preview = await client.post(
        "/api/v1/workspace-invitations/preview",
        json={"token": active_token},
    )
    assert revoked_preview.status_code == 404

    members = await client.get("/api/v1/workspace/members", headers=scoped_headers)
    owner = next(item for item in members.json() if item["isSelf"])
    remove_self = await client.delete(
        f"/api/v1/workspace/members/{owner['userId']}",
        headers=scoped_headers,
    )
    assert remove_self.status_code == 409
    change_self = await client.patch(
        f"/api/v1/workspace/members/{owner['userId']}",
        headers=scoped_headers,
        json={"role": "viewer", "allAgentsAccess": True, "agentIds": []},
    )
    assert change_self.status_code == 409
