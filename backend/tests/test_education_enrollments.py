from __future__ import annotations

from httpx import AsyncClient


async def _create_course(client: AsyncClient, headers: dict[str, str], code: str) -> dict:
    response = await client.post(
        "/api/v1/education/courses",
        headers=headers,
        json={"code": code, "name": f"{code} Course"},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _create_batch(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    course_id: str,
    code: str,
) -> dict:
    response = await client.post(
        "/api/v1/education/batches",
        headers=headers,
        json={
            "courseId": course_id,
            "code": code,
            "name": f"{code} Batch",
            "startsOn": "2026-09-01",
            "endsOn": "2027-06-30",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _create_student(client: AsyncClient, headers: dict[str, str], number: str) -> dict:
    response = await client.post(
        "/api/v1/education/students",
        headers=headers,
        json={"studentNumber": number, "name": f"Student {number}"},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _create_agent(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    name: str,
    purpose: str,
) -> dict:
    response = await client.post(
        "/api/v1/agents",
        headers=headers,
        json={
            "name": name,
            "description": "Enrollment test agent",
            "purpose": purpose,
            "deploymentChannel": "website",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_enrollment_lifecycle_integrity_and_workspace_isolation(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    workspace = await client.get("/api/v1/workspace", headers=auth_headers)
    assert workspace.status_code == 200, workspace.text
    workspace_id = workspace.json()["id"]
    headers = {**auth_headers, "X-Workspace-ID": workspace_id}

    course = await _create_course(client, headers, "ENR-CPA")
    batch = await _create_batch(client, headers, course_id=course["id"], code="ENR-CPA-A")
    student = await _create_student(client, headers, "ENR-1001")
    education_agent = await _create_agent(
        client,
        headers,
        name="Enrollment Education Agent",
        purpose="education",
    )
    support_agent = await _create_agent(
        client,
        headers,
        name="Enrollment Support Agent",
        purpose="support",
    )
    assert education_agent["status"] == "draft"

    non_education_agent = await client.post(
        "/api/v1/education/enrollments",
        headers=headers,
        json={
            "studentId": student["id"],
            "courseId": course["id"],
            "batchId": batch["id"],
            "agentId": support_agent["id"],
        },
    )
    assert non_education_agent.status_code == 422, non_education_agent.text

    invalid_dates = await client.post(
        "/api/v1/education/enrollments",
        headers=headers,
        json={
            "studentId": student["id"],
            "courseId": course["id"],
            "batchId": batch["id"],
            "agentId": education_agent["id"],
            "startsOn": "2027-01-01",
            "endsOn": "2026-12-31",
        },
    )
    assert invalid_dates.status_code == 422, invalid_dates.text

    other_course = await _create_course(client, headers, "ENR-ACCA")
    other_batch = await _create_batch(
        client,
        headers,
        course_id=other_course["id"],
        code="ENR-ACCA-A",
    )
    mismatched_batch = await client.post(
        "/api/v1/education/enrollments",
        headers=headers,
        json={
            "studentId": student["id"],
            "courseId": course["id"],
            "batchId": other_batch["id"],
            "agentId": education_agent["id"],
        },
    )
    assert mismatched_batch.status_code == 422, mismatched_batch.text

    created = await client.post(
        "/api/v1/education/enrollments",
        headers=headers,
        json={
            "studentId": student["id"],
            "courseId": course["id"],
            "batchId": batch["id"],
            "agentId": education_agent["id"],
            "startsOn": "2026-09-15",
            "endsOn": "2027-03-31",
        },
    )
    assert created.status_code == 201, created.text
    enrollment = created.json()
    enrollment_id = enrollment["id"]
    assert enrollment["workspaceId"] == workspace_id
    assert enrollment["studentId"] == student["id"]
    assert enrollment["courseId"] == course["id"]
    assert enrollment["batchId"] == batch["id"]
    assert enrollment["agentId"] == education_agent["id"]
    assert enrollment["status"] == "pending"
    assert enrollment["startsOn"] == "2026-09-15"
    assert enrollment["endsOn"] == "2027-03-31"

    duplicate = await client.post(
        "/api/v1/education/enrollments",
        headers=headers,
        json={
            "studentId": student["id"],
            "courseId": course["id"],
            "batchId": batch["id"],
            "agentId": education_agent["id"],
        },
    )
    assert duplicate.status_code == 409, duplicate.text

    listed = await client.get(
        f"/api/v1/education/enrollments?student_id={student['id']}&status=pending",
        headers=headers,
    )
    assert listed.status_code == 200, listed.text
    assert [item["id"] for item in listed.json()] == [enrollment_id]

    active = await client.patch(
        f"/api/v1/education/enrollments/{enrollment_id}",
        headers=headers,
        json={"status": "active"},
    )
    assert active.status_code == 200, active.text
    assert active.json()["status"] == "active"

    activate_agent = await client.patch(
        f"/api/v1/agents/{education_agent['id']}",
        headers=headers,
        json={"status": "active"},
    )
    assert activate_agent.status_code == 200, activate_agent.text
    assert activate_agent.json()["status"] == "active"

    assignment_change_while_active = await client.patch(
        f"/api/v1/education/enrollments/{enrollment_id}",
        headers=headers,
        json={"courseId": other_course["id"], "batchId": other_batch["id"]},
    )
    assert assignment_change_while_active.status_code == 409, assignment_change_while_active.text

    suspended = await client.patch(
        f"/api/v1/education/enrollments/{enrollment_id}",
        headers=headers,
        json={"status": "suspended"},
    )
    assert suspended.status_code == 200, suspended.text
    assert suspended.json()["status"] == "suspended"

    moved = await client.patch(
        f"/api/v1/education/enrollments/{enrollment_id}",
        headers=headers,
        json={"courseId": other_course["id"], "batchId": other_batch["id"]},
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["courseId"] == other_course["id"]
    assert moved.json()["batchId"] == other_batch["id"]

    reactivated = await client.patch(
        f"/api/v1/education/enrollments/{enrollment_id}",
        headers=headers,
        json={"status": "active", "startsOn": "2026-10-01", "endsOn": "2027-04-30"},
    )
    assert reactivated.status_code == 200, reactivated.text
    assert reactivated.json()["status"] == "active"
    assert reactivated.json()["startsOn"] == "2026-10-01"

    revoked = await client.delete(
        f"/api/v1/education/enrollments/{enrollment_id}",
        headers=headers,
    )
    assert revoked.status_code == 204, revoked.text

    revoked_record = await client.get(
        f"/api/v1/education/enrollments/{enrollment_id}",
        headers=headers,
    )
    assert revoked_record.status_code == 200, revoked_record.text
    assert revoked_record.json()["status"] == "revoked"

    restored = await client.patch(
        f"/api/v1/education/enrollments/{enrollment_id}",
        headers=headers,
        json={"status": "pending"},
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["status"] == "pending"

    active_again = await client.patch(
        f"/api/v1/education/enrollments/{enrollment_id}",
        headers=headers,
        json={"status": "active"},
    )
    assert active_again.status_code == 200, active_again.text

    graduated = await client.patch(
        f"/api/v1/education/enrollments/{enrollment_id}",
        headers=headers,
        json={"status": "graduated"},
    )
    assert graduated.status_code == 200, graduated.text
    assert graduated.json()["status"] == "graduated"

    reopen_graduated = await client.patch(
        f"/api/v1/education/enrollments/{enrollment_id}",
        headers=headers,
        json={"status": "active"},
    )
    assert reopen_graduated.status_code == 409, reopen_graduated.text

    revoke_graduated = await client.delete(
        f"/api/v1/education/enrollments/{enrollment_id}",
        headers=headers,
    )
    assert revoke_graduated.status_code == 409, revoke_graduated.text

    secondary_workspace = await client.post(
        "/api/v1/workspaces",
        headers=auth_headers,
        json={"name": "Enrollment Isolation", "slug": "enrollment-isolation"},
    )
    assert secondary_workspace.status_code in {201, 409}, secondary_workspace.text
    if secondary_workspace.status_code == 201:
        secondary_id = secondary_workspace.json()["id"]
    else:
        workspaces = await client.get("/api/v1/workspaces", headers=auth_headers)
        assert workspaces.status_code == 200, workspaces.text
        secondary_id = next(
            item["id"] for item in workspaces.json() if item["slug"] == "enrollment-isolation"
        )
    secondary_headers = {**auth_headers, "X-Workspace-ID": secondary_id}

    cross_workspace_get = await client.get(
        f"/api/v1/education/enrollments/{enrollment_id}",
        headers=secondary_headers,
    )
    assert cross_workspace_get.status_code == 404, cross_workspace_get.text

    cross_workspace_create = await client.post(
        "/api/v1/education/enrollments",
        headers=secondary_headers,
        json={
            "studentId": student["id"],
            "courseId": course["id"],
            "batchId": batch["id"],
            "agentId": education_agent["id"],
        },
    )
    assert cross_workspace_create.status_code == 404, cross_workspace_create.text


async def test_archived_student_enrollment_history_is_read_only(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    workspace = await client.get("/api/v1/workspace", headers=auth_headers)
    assert workspace.status_code == 200, workspace.text
    headers = {**auth_headers, "X-Workspace-ID": workspace.json()["id"]}

    course = await _create_course(client, headers, "ENR-ARCHIVE")
    batch = await _create_batch(
        client,
        headers,
        course_id=course["id"],
        code="ENR-ARCHIVE-A",
    )
    student = await _create_student(client, headers, "ENR-ARCHIVE-1001")
    education_agent = await _create_agent(
        client,
        headers,
        name="Archived Student Education Agent",
        purpose="education",
    )

    created = await client.post(
        "/api/v1/education/enrollments",
        headers=headers,
        json={
            "studentId": student["id"],
            "courseId": course["id"],
            "batchId": batch["id"],
            "agentId": education_agent["id"],
            "startsOn": "2026-09-15",
            "endsOn": "2027-03-31",
        },
    )
    assert created.status_code == 201, created.text
    enrollment_id = created.json()["id"]

    expired = await client.patch(
        f"/api/v1/education/enrollments/{enrollment_id}",
        headers=headers,
        json={"status": "expired"},
    )
    assert expired.status_code == 200, expired.text
    assert expired.json()["status"] == "expired"

    archived = await client.delete(
        f"/api/v1/education/students/{student['id']}",
        headers=headers,
    )
    assert archived.status_code == 204, archived.text

    history = await client.get(
        f"/api/v1/education/enrollments/{enrollment_id}",
        headers=headers,
    )
    assert history.status_code == 200, history.text
    assert history.json()["status"] == "expired"

    edit_archived_history = await client.patch(
        f"/api/v1/education/enrollments/{enrollment_id}",
        headers=headers,
        json={"endsOn": "2027-04-30"},
    )
    assert edit_archived_history.status_code == 409, edit_archived_history.text
    assert "Reactivate the Student" in edit_archived_history.json()["error"]["message"]

    revoke_archived_history = await client.delete(
        f"/api/v1/education/enrollments/{enrollment_id}",
        headers=headers,
    )
    assert revoke_archived_history.status_code == 409, revoke_archived_history.text
    assert "Reactivate the Student" in revoke_archived_history.json()["error"]["message"]

    unchanged_history = await client.get(
        f"/api/v1/education/enrollments/{enrollment_id}",
        headers=headers,
    )
    assert unchanged_history.status_code == 200, unchanged_history.text
    assert unchanged_history.json()["status"] == "expired"
    assert unchanged_history.json()["endsOn"] == "2027-03-31"
