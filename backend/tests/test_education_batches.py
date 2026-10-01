from __future__ import annotations

from httpx import AsyncClient


async def test_batch_lifecycle_is_workspace_and_course_scoped(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    original_workspace = await client.get("/api/v1/workspace", headers=auth_headers)
    assert original_workspace.status_code == 200, original_workspace.text
    original_id = original_workspace.json()["id"]
    original_headers = {**auth_headers, "X-Workspace-ID": original_id}

    course_response = await client.post(
        "/api/v1/education/courses",
        headers=original_headers,
        json={"code": "CPA-CORE", "name": "CPA Core"},
    )
    assert course_response.status_code == 201, course_response.text
    course_id = course_response.json()["id"]

    created = await client.post(
        "/api/v1/education/batches",
        headers=original_headers,
        json={
            "courseId": course_id,
            "code": " cpa-2026-a ",
            "name": "CPA 2026 Cohort A",
            "description": "Morning cohort",
            "startsOn": "2026-09-15",
            "endsOn": "2027-03-31",
        },
    )
    assert created.status_code == 201, created.text
    batch = created.json()
    assert batch["code"] == "CPA-2026-A"
    assert batch["courseId"] == course_id
    assert batch["workspaceId"] == original_id
    assert batch["status"] == "active"
    assert batch["startsOn"] == "2026-09-15"
    assert batch["endsOn"] == "2027-03-31"
    batch_id = batch["id"]

    duplicate = await client.post(
        "/api/v1/education/batches",
        headers=original_headers,
        json={
            "courseId": course_id,
            "code": "CPA-2026-A",
            "name": "Duplicate batch",
        },
    )
    assert duplicate.status_code == 409, duplicate.text

    invalid_range = await client.post(
        "/api/v1/education/batches",
        headers=original_headers,
        json={
            "courseId": course_id,
            "code": "CPA-BAD-DATES",
            "name": "Invalid dates",
            "startsOn": "2026-12-01",
            "endsOn": "2026-11-01",
        },
    )
    assert invalid_range.status_code == 422, invalid_range.text

    listed = await client.get(
        f"/api/v1/education/batches?course_id={course_id}&status=active&search=cohort",
        headers=original_headers,
    )
    assert listed.status_code == 200, listed.text
    assert any(item["id"] == batch_id for item in listed.json())

    updated = await client.patch(
        f"/api/v1/education/batches/{batch_id}",
        headers=original_headers,
        json={
            "name": "CPA 2026 Cohort Alpha",
            "description": "Updated morning cohort",
            "endsOn": "2027-04-15",
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["name"] == "CPA 2026 Cohort Alpha"
    assert updated.json()["endsOn"] == "2027-04-15"

    invalid_patch = await client.patch(
        f"/api/v1/education/batches/{batch_id}",
        headers=original_headers,
        json={"endsOn": "2026-01-01"},
    )
    assert invalid_patch.status_code == 422, invalid_patch.text

    blocked_course_archive = await client.delete(
        f"/api/v1/education/courses/{course_id}",
        headers=original_headers,
    )
    assert blocked_course_archive.status_code == 409, blocked_course_archive.text

    archived = await client.delete(
        f"/api/v1/education/batches/{batch_id}",
        headers=original_headers,
    )
    assert archived.status_code == 204, archived.text

    archived_batch = await client.get(
        f"/api/v1/education/batches/{batch_id}",
        headers=original_headers,
    )
    assert archived_batch.status_code == 200, archived_batch.text
    assert archived_batch.json()["status"] == "archived"

    course_archived = await client.delete(
        f"/api/v1/education/courses/{course_id}",
        headers=original_headers,
    )
    assert course_archived.status_code == 204, course_archived.text

    create_under_archived_course = await client.post(
        "/api/v1/education/batches",
        headers=original_headers,
        json={
            "courseId": course_id,
            "code": "CPA-2026-B",
            "name": "CPA 2026 Cohort B",
        },
    )
    assert create_under_archived_course.status_code == 409, create_under_archived_course.text

    reactivate_under_archived_course = await client.patch(
        f"/api/v1/education/batches/{batch_id}",
        headers=original_headers,
        json={"status": "active"},
    )
    assert reactivate_under_archived_course.status_code == 409, reactivate_under_archived_course.text

    course_reactivated = await client.patch(
        f"/api/v1/education/courses/{course_id}",
        headers=original_headers,
        json={"status": "active"},
    )
    assert course_reactivated.status_code == 200, course_reactivated.text

    batch_reactivated = await client.patch(
        f"/api/v1/education/batches/{batch_id}",
        headers=original_headers,
        json={"status": "active"},
    )
    assert batch_reactivated.status_code == 200, batch_reactivated.text
    assert batch_reactivated.json()["status"] == "active"

    secondary_workspace = await client.post(
        "/api/v1/workspaces",
        headers=auth_headers,
        json={"name": "Education Batch Isolation", "slug": "education-batch-isolation"},
    )
    assert secondary_workspace.status_code in {201, 409}, secondary_workspace.text
    if secondary_workspace.status_code == 201:
        secondary_id = secondary_workspace.json()["id"]
    else:
        workspaces = await client.get("/api/v1/workspaces", headers=auth_headers)
        assert workspaces.status_code == 200, workspaces.text
        secondary_id = next(
            item["id"] for item in workspaces.json() if item["slug"] == "education-batch-isolation"
        )
    secondary_headers = {**auth_headers, "X-Workspace-ID": secondary_id}

    cross_workspace_course = await client.post(
        "/api/v1/education/batches",
        headers=secondary_headers,
        json={
            "courseId": course_id,
            "code": "CPA-2026-A",
            "name": "Cross workspace batch",
        },
    )
    assert cross_workspace_course.status_code == 404, cross_workspace_course.text

    secondary_course_response = await client.post(
        "/api/v1/education/courses",
        headers=secondary_headers,
        json={"code": "CPA-CORE", "name": "Secondary CPA Core"},
    )
    assert secondary_course_response.status_code == 201, secondary_course_response.text
    secondary_course_id = secondary_course_response.json()["id"]

    same_code_other_workspace = await client.post(
        "/api/v1/education/batches",
        headers=secondary_headers,
        json={
            "courseId": secondary_course_id,
            "code": "CPA-2026-A",
            "name": "Secondary CPA 2026 Cohort A",
        },
    )
    assert same_code_other_workspace.status_code == 201, same_code_other_workspace.text
    secondary_batch = same_code_other_workspace.json()
    assert secondary_batch["workspaceId"] == secondary_id

    secondary_list = await client.get("/api/v1/education/batches", headers=secondary_headers)
    assert secondary_list.status_code == 200, secondary_list.text
    assert all(item["workspaceId"] == secondary_id for item in secondary_list.json())
    assert all(item["id"] != batch_id for item in secondary_list.json())

    cross_workspace_get = await client.get(
        f"/api/v1/education/batches/{secondary_batch['id']}",
        headers=original_headers,
    )
    assert cross_workspace_get.status_code == 404, cross_workspace_get.text
