from __future__ import annotations

from httpx import AsyncClient


async def test_student_lifecycle_is_workspace_scoped(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    original_workspace = await client.get("/api/v1/workspace", headers=auth_headers)
    assert original_workspace.status_code == 200, original_workspace.text
    original_id = original_workspace.json()["id"]
    original_headers = {**auth_headers, "X-Workspace-ID": original_id}

    created = await client.post(
        "/api/v1/education/students",
        headers=original_headers,
        json={
            "studentNumber": " ns-1001 ",
            "name": "  Asha   Verma ",
            "email": "ASHA@example.com",
            "customFields": {"language": "English", "city": "Patna"},
        },
    )
    assert created.status_code == 201, created.text
    student = created.json()
    assert student["studentNumber"] == "NS-1001"
    assert student["name"] == "Asha Verma"
    assert student["email"] == "asha@example.com"
    assert student["customFields"] == {"language": "English", "city": "Patna"}
    assert student["status"] == "active"
    assert student["workspaceId"] == original_id
    student_id = student["id"]

    duplicate = await client.post(
        "/api/v1/education/students",
        headers=original_headers,
        json={"studentNumber": "ns-1001", "name": "Duplicate Student"},
    )
    assert duplicate.status_code == 409, duplicate.text

    invalid = await client.post(
        "/api/v1/education/students",
        headers=original_headers,
        json={"studentNumber": "bad student id!", "name": "Invalid Student"},
    )
    assert invalid.status_code == 422, invalid.text

    invalid_nested_custom_field = await client.post(
        "/api/v1/education/students",
        headers=original_headers,
        json={
            "studentNumber": "NS-1002",
            "name": "Nested Value",
            "customFields": {"unsafe": {"nested": "value"}},
        },
    )
    assert invalid_nested_custom_field.status_code == 422, invalid_nested_custom_field.text

    listed = await client.get(
        "/api/v1/education/students?status=active&search=asha",
        headers=original_headers,
    )
    assert listed.status_code == 200, listed.text
    assert any(item["id"] == student_id for item in listed.json())

    updated = await client.patch(
        f"/api/v1/education/students/{student_id}",
        headers=original_headers,
        json={
            "name": "Asha V. Sharma",
            "email": "asha.sharma@example.com",
            "customFields": {"language": "Hindi", "city": "Delhi", "level": "L2"},
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["name"] == "Asha V. Sharma"
    assert updated.json()["email"] == "asha.sharma@example.com"
    assert updated.json()["customFields"]["level"] == "L2"

    archived = await client.delete(
        f"/api/v1/education/students/{student_id}",
        headers=original_headers,
    )
    assert archived.status_code == 204, archived.text

    archived_student = await client.get(
        f"/api/v1/education/students/{student_id}",
        headers=original_headers,
    )
    assert archived_student.status_code == 200, archived_student.text
    assert archived_student.json()["status"] == "archived"

    active_only = await client.get(
        "/api/v1/education/students?status=active",
        headers=original_headers,
    )
    assert active_only.status_code == 200, active_only.text
    assert all(item["id"] != student_id for item in active_only.json())

    reactivated = await client.patch(
        f"/api/v1/education/students/{student_id}",
        headers=original_headers,
        json={"status": "active"},
    )
    assert reactivated.status_code == 200, reactivated.text
    assert reactivated.json()["status"] == "active"

    secondary_workspace = await client.post(
        "/api/v1/workspaces",
        headers=auth_headers,
        json={"name": "Education Student Isolation", "slug": "education-student-isolation"},
    )
    assert secondary_workspace.status_code in {201, 409}, secondary_workspace.text
    if secondary_workspace.status_code == 201:
        secondary_id = secondary_workspace.json()["id"]
    else:
        workspaces = await client.get("/api/v1/workspaces", headers=auth_headers)
        assert workspaces.status_code == 200, workspaces.text
        secondary_id = next(
            item["id"] for item in workspaces.json() if item["slug"] == "education-student-isolation"
        )
    secondary_headers = {**auth_headers, "X-Workspace-ID": secondary_id}

    same_student_number_other_workspace = await client.post(
        "/api/v1/education/students",
        headers=secondary_headers,
        json={"studentNumber": "NS-1001", "name": "Secondary Asha"},
    )
    assert same_student_number_other_workspace.status_code == 201, same_student_number_other_workspace.text
    secondary_student = same_student_number_other_workspace.json()
    assert secondary_student["workspaceId"] == secondary_id

    secondary_list = await client.get("/api/v1/education/students", headers=secondary_headers)
    assert secondary_list.status_code == 200, secondary_list.text
    assert all(item["workspaceId"] == secondary_id for item in secondary_list.json())
    assert all(item["id"] != student_id for item in secondary_list.json())

    cross_workspace_get = await client.get(
        f"/api/v1/education/students/{secondary_student['id']}",
        headers=original_headers,
    )
    assert cross_workspace_get.status_code == 404, cross_workspace_get.text


async def test_student_whatsapp_profile_creates_identity_atomically(client, auth_headers):
    payload = {"studentNumber": "WA-PROFILE", "name": "WhatsApp Student", "whatsappNumber": "+91 98765 40123"}
    created = await client.post("/api/v1/education/students", headers=auth_headers, json=payload)
    assert created.status_code == 201, created.text
    student = created.json()
    assert student["whatsappNumber"] == "+919876540123"
    assert student["whatsappVerified"] is False
    updated = await client.patch(
        f"/api/v1/education/students/{student['id']}",
        headers=auth_headers,
        json={"whatsappNumber": "+919876540123", "whatsappVerified": True},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["whatsappVerified"] is True
    duplicate = await client.post(
        "/api/v1/education/students", headers=auth_headers, json={**payload, "studentNumber": "WA-DUPLICATE"}
    )
    assert duplicate.status_code == 409, duplicate.text
    listed = (await client.get("/api/v1/education/students", headers=auth_headers)).json()
    assert not any(item["studentNumber"] == "WA-DUPLICATE" for item in listed)
    changed = await client.patch(
        f"/api/v1/education/students/{student['id']}",
        headers=auth_headers,
        json={"whatsappNumber": "+919876540124"},
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["whatsappVerified"] is False
    identities = (
        await client.get(f"/api/v1/education/students/{student['id']}/identities", headers=auth_headers)
    ).json()
    assert (
        next(item for item in identities if item["normalizedIdentifier"] == "+919876540123")["status"]
        == "revoked"
    )
    invalid = await client.patch(
        f"/api/v1/education/students/{student['id']}", headers=auth_headers, json={"whatsappNumber": "98765"}
    )
    assert invalid.status_code == 422


async def test_student_telegram_profile_creates_and_verifies_identity_atomically(client, auth_headers):
    created = await client.post(
        "/api/v1/education/students",
        headers=auth_headers,
        json={
            "studentNumber": "TG-PROFILE",
            "name": "Telegram Student",
            "telegramUserId": "123456789",
        },
    )
    assert created.status_code == 201, created.text
    student = created.json()
    assert student["telegramUserId"] == "123456789"
    assert student["telegramVerified"] is False

    verified = await client.patch(
        f"/api/v1/education/students/{student['id']}",
        headers=auth_headers,
        json={"telegramUserId": "123456789", "telegramVerified": True},
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["telegramVerified"] is True

    duplicate = await client.post(
        "/api/v1/education/students",
        headers=auth_headers,
        json={
            "studentNumber": "TG-DUPLICATE",
            "name": "Duplicate Telegram Student",
            "telegramUserId": "123456789",
        },
    )
    assert duplicate.status_code == 409, duplicate.text

    changed = await client.patch(
        f"/api/v1/education/students/{student['id']}",
        headers=auth_headers,
        json={"telegramUserId": "123456781"},
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["telegramUserId"] == "123456781"
    assert changed.json()["telegramVerified"] is False

    identities = (
        await client.get(f"/api/v1/education/students/{student['id']}/identities", headers=auth_headers)
    ).json()
    old_identity = next(item for item in identities if item["normalizedIdentifier"] == "123456789")
    assert old_identity["status"] == "revoked"

    invalid = await client.patch(
        f"/api/v1/education/students/{student['id']}",
        headers=auth_headers,
        json={"telegramUserId": "@student"},
    )
    assert invalid.status_code == 422
