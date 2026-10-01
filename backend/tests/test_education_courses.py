from __future__ import annotations

from httpx import AsyncClient

from northstar_api.models import WorkspaceRole
from northstar_api.security import WORKSPACE_ROLE_PERMISSIONS


async def test_course_lifecycle_is_workspace_scoped(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    original_workspace = await client.get("/api/v1/workspace", headers=auth_headers)
    assert original_workspace.status_code == 200, original_workspace.text
    original_id = original_workspace.json()["id"]
    original_headers = {**auth_headers, "X-Workspace-ID": original_id}

    created = await client.post(
        "/api/v1/education/courses",
        headers=original_headers,
        json={
            "code": " cma-foundations ",
            "name": "CMA Foundations",
            "description": "Core CMA preparation course",
        },
    )
    assert created.status_code == 201, created.text
    course = created.json()
    assert course["code"] == "CMA-FOUNDATIONS"
    assert course["name"] == "CMA Foundations"
    assert course["status"] == "active"
    assert course["workspaceId"] == original_id
    course_id = course["id"]

    duplicate = await client.post(
        "/api/v1/education/courses",
        headers=original_headers,
        json={"code": "cma-foundations", "name": "Duplicate CMA"},
    )
    assert duplicate.status_code == 409, duplicate.text

    invalid = await client.post(
        "/api/v1/education/courses",
        headers=original_headers,
        json={"code": "bad course!", "name": "Invalid Code"},
    )
    assert invalid.status_code == 422, invalid.text

    listed = await client.get(
        "/api/v1/education/courses?status=active&search=foundations",
        headers=original_headers,
    )
    assert listed.status_code == 200, listed.text
    assert any(item["id"] == course_id for item in listed.json())

    updated = await client.patch(
        f"/api/v1/education/courses/{course_id}",
        headers=original_headers,
        json={"name": "CMA Foundation Program", "description": "Updated course catalog entry"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["name"] == "CMA Foundation Program"
    assert updated.json()["description"] == "Updated course catalog entry"

    archived = await client.delete(
        f"/api/v1/education/courses/{course_id}",
        headers=original_headers,
    )
    assert archived.status_code == 204, archived.text

    archived_course = await client.get(
        f"/api/v1/education/courses/{course_id}",
        headers=original_headers,
    )
    assert archived_course.status_code == 200, archived_course.text
    assert archived_course.json()["status"] == "archived"

    active_only = await client.get(
        "/api/v1/education/courses?status=active",
        headers=original_headers,
    )
    assert active_only.status_code == 200, active_only.text
    assert all(item["id"] != course_id for item in active_only.json())

    reactivated = await client.patch(
        f"/api/v1/education/courses/{course_id}",
        headers=original_headers,
        json={"status": "active"},
    )
    assert reactivated.status_code == 200, reactivated.text
    assert reactivated.json()["status"] == "active"

    secondary_workspace = await client.post(
        "/api/v1/workspaces",
        headers=auth_headers,
        json={"name": "Education Course Isolation", "slug": "education-course-isolation"},
    )
    assert secondary_workspace.status_code in {201, 409}, secondary_workspace.text
    if secondary_workspace.status_code == 201:
        secondary_id = secondary_workspace.json()["id"]
    else:
        workspaces = await client.get("/api/v1/workspaces", headers=auth_headers)
        assert workspaces.status_code == 200, workspaces.text
        secondary_id = next(
            item["id"] for item in workspaces.json() if item["slug"] == "education-course-isolation"
        )
    secondary_headers = {**auth_headers, "X-Workspace-ID": secondary_id}

    same_code_other_workspace = await client.post(
        "/api/v1/education/courses",
        headers=secondary_headers,
        json={"code": "CMA-FOUNDATIONS", "name": "Secondary CMA Foundations"},
    )
    assert same_code_other_workspace.status_code == 201, same_code_other_workspace.text
    secondary_course = same_code_other_workspace.json()
    assert secondary_course["workspaceId"] == secondary_id

    secondary_list = await client.get("/api/v1/education/courses", headers=secondary_headers)
    assert secondary_list.status_code == 200, secondary_list.text
    assert all(item["workspaceId"] == secondary_id for item in secondary_list.json())
    assert all(item["id"] != course_id for item in secondary_list.json())

    cross_workspace_get = await client.get(
        f"/api/v1/education/courses/{secondary_course['id']}",
        headers=original_headers,
    )
    assert cross_workspace_get.status_code == 404, cross_workspace_get.text


def test_course_permissions_are_separated_by_workspace_role() -> None:
    manager = WORKSPACE_ROLE_PERMISSIONS[WorkspaceRole.MANAGER]
    operator = WORKSPACE_ROLE_PERMISSIONS[WorkspaceRole.OPERATOR]
    analyst = WORKSPACE_ROLE_PERMISSIONS[WorkspaceRole.ANALYST]
    viewer = WORKSPACE_ROLE_PERMISSIONS[WorkspaceRole.VIEWER]

    assert {"education.view", "education.manage"}.issubset(manager)
    assert "education.view" in operator and "education.manage" not in operator
    assert "education.view" in analyst and "education.manage" not in analyst
    assert "education.view" in viewer and "education.manage" not in viewer
