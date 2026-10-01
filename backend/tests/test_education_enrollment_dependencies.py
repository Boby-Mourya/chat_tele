from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.parametrize("delete_with_enrollment", [False, True])
async def test_non_terminal_enrollment_protects_student_course_batch_and_agent(
    delete_with_enrollment: bool,
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    workspace = await client.get("/api/v1/workspace", headers=auth_headers)
    assert workspace.status_code == 200, workspace.text
    workspace_id = workspace.json()["id"]
    headers = {**auth_headers, "X-Workspace-ID": workspace_id}

    course_response = await client.post(
        "/api/v1/education/courses",
        headers=headers,
        json={"code": f"ENR-GUARD-{delete_with_enrollment}", "name": "Enrollment Guard Course"},
    )
    assert course_response.status_code == 201, course_response.text
    course = course_response.json()

    batch_response = await client.post(
        "/api/v1/education/batches",
        headers=headers,
        json={
            "courseId": course["id"],
            "code": f"ENR-GUARD-A-{delete_with_enrollment}",
            "name": "Enrollment Guard Batch",
        },
    )
    assert batch_response.status_code == 201, batch_response.text
    batch = batch_response.json()

    student_response = await client.post(
        "/api/v1/education/students",
        headers=headers,
        json={"studentNumber": f"ENR-GUARD-{delete_with_enrollment}", "name": "Guard Student"},
    )
    assert student_response.status_code == 201, student_response.text
    student = student_response.json()

    agent_response = await client.post(
        "/api/v1/agents",
        headers=headers,
        json={
            "name": f"Enrollment Guard Education Agent {delete_with_enrollment}",
            "description": "Guarded by enrollment dependencies",
            "purpose": "education",
            "deploymentChannel": "website",
        },
    )
    assert agent_response.status_code == 201, agent_response.text
    agent = agent_response.json()

    activate_before_enrollment = await client.patch(
        f"/api/v1/agents/{agent['id']}",
        headers=headers,
        json={"status": "active"},
    )
    assert activate_before_enrollment.status_code == 409, activate_before_enrollment.text

    enrollment_response = await client.post(
        "/api/v1/education/enrollments",
        headers=headers,
        json={
            "studentId": student["id"],
            "courseId": course["id"],
            "batchId": batch["id"],
            "agentId": agent["id"],
            "status": "active",
        },
    )
    assert enrollment_response.status_code == 201, enrollment_response.text
    enrollment = enrollment_response.json()

    activate_after_enrollment = await client.patch(
        f"/api/v1/agents/{agent['id']}",
        headers=headers,
        json={"status": "active"},
    )
    assert activate_after_enrollment.status_code == 200, activate_after_enrollment.text

    archive_student = await client.delete(
        f"/api/v1/education/students/{student['id']}",
        headers=headers,
    )
    assert archive_student.status_code == 409, archive_student.text

    archive_batch = await client.delete(
        f"/api/v1/education/batches/{batch['id']}",
        headers=headers,
    )
    assert archive_batch.status_code == 409, archive_batch.text

    archive_course = await client.delete(
        f"/api/v1/education/courses/{course['id']}",
        headers=headers,
    )
    assert archive_course.status_code == 409, archive_course.text

    change_agent_purpose = await client.patch(
        f"/api/v1/agents/{agent['id']}",
        headers=headers,
        json={"purpose": "support"},
    )
    assert change_agent_purpose.status_code == 409, change_agent_purpose.text

    if delete_with_enrollment:
        deleted = await client.delete(f"/api/v1/agents/{agent['id']}", headers=headers)
        assert deleted.status_code == 204, deleted.text
        missing = await client.get(f"/api/v1/agents/{agent['id']}", headers=headers)
        assert missing.status_code == 404
        from uuid import UUID
        from northstar_api.database import SessionFactory
        from northstar_api.education_enrollments import EducationEnrollment
        async with SessionFactory() as session:
            retained = await session.get(EducationEnrollment, UUID(enrollment['id']))
            assert retained is not None
            assert retained.status == 'revoked'
        return

    graduate = await client.patch(
        f"/api/v1/education/enrollments/{enrollment['id']}",
        headers=headers,
        json={"status": "graduated"},
    )
    assert graduate.status_code == 200, graduate.text

    change_after_terminal = await client.patch(
        f"/api/v1/agents/{agent['id']}",
        headers=headers,
        json={"purpose": "support", "status": "draft"},
    )
    assert change_after_terminal.status_code == 200, change_after_terminal.text
    assert change_after_terminal.json()["purpose"] == "support"

    archive_student_after_terminal = await client.delete(
        f"/api/v1/education/students/{student['id']}",
        headers=headers,
    )
    assert archive_student_after_terminal.status_code == 204, archive_student_after_terminal.text

    archive_batch_after_terminal = await client.delete(
        f"/api/v1/education/batches/{batch['id']}",
        headers=headers,
    )
    assert archive_batch_after_terminal.status_code == 204, archive_batch_after_terminal.text

    archive_course_after_terminal = await client.delete(
        f"/api/v1/education/courses/{course['id']}",
        headers=headers,
    )
    assert archive_course_after_terminal.status_code == 204, archive_course_after_terminal.text
