from __future__ import annotations

from httpx import AsyncClient


async def _create_student(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    student_number: str,
    name: str,
) -> dict:
    response = await client.post(
        "/api/v1/education/students",
        headers=headers,
        json={"studentNumber": student_number, "name": name},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_student_identity_lifecycle_and_workspace_isolation(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    workspace = await client.get("/api/v1/workspace", headers=auth_headers)
    assert workspace.status_code == 200, workspace.text
    workspace_id = workspace.json()["id"]
    headers = {**auth_headers, "X-Workspace-ID": workspace_id}

    first_student = await _create_student(
        client,
        headers,
        student_number="IDENTITY-1001",
        name="Asha Identity",
    )
    second_student = await _create_student(
        client,
        headers,
        student_number="IDENTITY-1002",
        name="Riya Identity",
    )

    whatsapp = await client.post(
        f"/api/v1/education/students/{first_student['id']}/identities",
        headers=headers,
        json={
            "identityType": "whatsapp",
            "identifier": "+91 98765-43210",
            "label": "Primary WhatsApp",
            "status": "verified",
        },
    )
    assert whatsapp.status_code == 201, whatsapp.text
    whatsapp_identity = whatsapp.json()
    assert whatsapp_identity["identifier"] == "+919876543210"
    assert whatsapp_identity["normalizedIdentifier"] == "+919876543210"
    assert whatsapp_identity["status"] == "verified"
    assert whatsapp_identity["isPrimary"] is True
    assert whatsapp_identity["verifiedAt"] is not None

    secondary_whatsapp = await client.post(
        f"/api/v1/education/students/{first_student['id']}/identities",
        headers=headers,
        json={
            "identityType": "whatsapp",
            "identifier": "0091 91234 56789",
            "label": "Backup WhatsApp",
        },
    )
    assert secondary_whatsapp.status_code == 201, secondary_whatsapp.text
    secondary_identity = secondary_whatsapp.json()
    assert secondary_identity["identifier"] == "+919123456789"
    assert secondary_identity["status"] == "pending"
    assert secondary_identity["isPrimary"] is False

    make_primary = await client.patch(
        f"/api/v1/education/students/{first_student['id']}/identities/{secondary_identity['id']}",
        headers=headers,
        json={"isPrimary": True},
    )
    assert make_primary.status_code == 200, make_primary.text
    assert make_primary.json()["isPrimary"] is True

    identities = await client.get(
        f"/api/v1/education/students/{first_student['id']}/identities?type=whatsapp",
        headers=headers,
    )
    assert identities.status_code == 200, identities.text
    by_id = {item["id"]: item for item in identities.json()}
    assert by_id[secondary_identity["id"]]["isPrimary"] is True
    assert by_id[whatsapp_identity["id"]]["isPrimary"] is False

    duplicate_identity = await client.post(
        f"/api/v1/education/students/{second_student['id']}/identities",
        headers=headers,
        json={"identityType": "whatsapp", "identifier": "+91 (98765) 43210"},
    )
    assert duplicate_identity.status_code == 409, duplicate_identity.text

    invalid_phone = await client.post(
        f"/api/v1/education/students/{first_student['id']}/identities",
        headers=headers,
        json={"identityType": "alternate_phone", "identifier": "98765"},
    )
    assert invalid_phone.status_code == 422, invalid_phone.text

    invalid_telegram = await client.post(
        f"/api/v1/education/students/{first_student['id']}/identities",
        headers=headers,
        json={"identityType": "telegram", "identifier": "@asha"},
    )
    assert invalid_telegram.status_code == 422, invalid_telegram.text

    telegram = await client.post(
        f"/api/v1/education/students/{first_student['id']}/identities",
        headers=headers,
        json={"identityType": "telegram", "identifier": "123456789", "label": "Telegram"},
    )
    assert telegram.status_code == 201, telegram.text
    telegram_identity = telegram.json()
    assert telegram_identity["status"] == "pending"
    assert telegram_identity["isPrimary"] is True

    verified_telegram = await client.patch(
        f"/api/v1/education/students/{first_student['id']}/identities/{telegram_identity['id']}",
        headers=headers,
        json={"status": "verified"},
    )
    assert verified_telegram.status_code == 200, verified_telegram.text
    assert verified_telegram.json()["status"] == "verified"
    assert verified_telegram.json()["verifiedAt"] is not None

    revoked = await client.delete(
        f"/api/v1/education/students/{first_student['id']}/identities/{secondary_identity['id']}",
        headers=headers,
    )
    assert revoked.status_code == 204, revoked.text

    after_revoke = await client.get(
        f"/api/v1/education/students/{first_student['id']}/identities?type=whatsapp",
        headers=headers,
    )
    assert after_revoke.status_code == 200, after_revoke.text
    after_by_id = {item["id"]: item for item in after_revoke.json()}
    assert after_by_id[secondary_identity["id"]]["status"] == "revoked"
    assert after_by_id[secondary_identity["id"]]["isPrimary"] is False
    assert after_by_id[whatsapp_identity["id"]]["isPrimary"] is True

    restored = await client.patch(
        f"/api/v1/education/students/{first_student['id']}/identities/{secondary_identity['id']}",
        headers=headers,
        json={"status": "pending"},
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["status"] == "pending"
    assert restored.json()["verifiedAt"] is None

    second_workspace = await client.post(
        "/api/v1/workspaces",
        headers=auth_headers,
        json={"name": "Identity Isolation", "slug": "identity-isolation"},
    )
    assert second_workspace.status_code in {201, 409}, second_workspace.text
    if second_workspace.status_code == 201:
        second_workspace_id = second_workspace.json()["id"]
    else:
        workspaces = await client.get("/api/v1/workspaces", headers=auth_headers)
        assert workspaces.status_code == 200, workspaces.text
        second_workspace_id = next(
            item["id"] for item in workspaces.json() if item["slug"] == "identity-isolation"
        )
    second_headers = {**auth_headers, "X-Workspace-ID": second_workspace_id}
    same_student_other_workspace = await _create_student(
        client,
        second_headers,
        student_number="IDENTITY-1001",
        name="Workspace Two Student",
    )
    same_identity_other_workspace = await client.post(
        f"/api/v1/education/students/{same_student_other_workspace['id']}/identities",
        headers=second_headers,
        json={"identityType": "whatsapp", "identifier": "+919876543210", "status": "verified"},
    )
    assert same_identity_other_workspace.status_code == 201, same_identity_other_workspace.text
    assert same_identity_other_workspace.json()["workspaceId"] == second_workspace_id

    cross_workspace_list = await client.get(
        f"/api/v1/education/students/{same_student_other_workspace['id']}/identities",
        headers=headers,
    )
    assert cross_workspace_list.status_code == 404, cross_workspace_list.text

    archived = await client.delete(
        f"/api/v1/education/students/{second_student['id']}",
        headers=headers,
    )
    assert archived.status_code == 204, archived.text
    blocked_on_archived_student = await client.post(
        f"/api/v1/education/students/{second_student['id']}/identities",
        headers=headers,
        json={"identityType": "website_login", "identifier": "riya.student"},
    )
    assert blocked_on_archived_student.status_code == 409, blocked_on_archived_student.text
