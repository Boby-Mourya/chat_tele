from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.agent_purpose import AgentPurpose, get_agent_purpose
from northstar_api.education import CourseStatus, EducationCourse
from northstar_api.education_batches import BatchStatus, EducationBatch
from northstar_api.education_enrollments import EducationEnrollment
from northstar_api.education_student_identities import (
    EducationStudentIdentity,
    StudentIdentityStatus,
)
from northstar_api.education_student_import_schemas import (
    StudentImportCommitResult,
    StudentImportPreview,
    StudentImportRow,
    StudentImportRowPreview,
)
from northstar_api.education_students import EducationStudent, StudentStatus
from northstar_api.models import Agent, AgentStatus
from northstar_api.services.outbox import enqueue_event
from northstar_api.services.student_identity import normalize_student_identity


class StudentImportConflictError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ResolvedStudentImportRow:
    row: StudentImportRow
    normalized_identifier: str | None = None
    course_id: UUID | None = None
    batch_id: UUID | None = None
    agent_id: UUID | None = None


async def validate_student_import(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    rows: list[StudentImportRow],
) -> tuple[StudentImportPreview, list[ResolvedStudentImportRow]]:
    existing_students = (
        await session.execute(
            select(EducationStudent.student_number, EducationStudent.email).where(
                EducationStudent.tenant_id == tenant_id,
                EducationStudent.workspace_id == workspace_id,
            )
        )
    ).all()
    existing_student_numbers = {student_number for student_number, _ in existing_students}
    existing_emails = {email.lower() for _, email in existing_students if email}
    existing_identity_rows = (
        await session.execute(
            select(
                EducationStudentIdentity.identity_type,
                EducationStudentIdentity.normalized_identifier,
            ).where(
                EducationStudentIdentity.tenant_id == tenant_id,
                EducationStudentIdentity.workspace_id == workspace_id,
            )
        )
    ).all()
    existing_identity_keys = {
        (identity_type, normalized_identifier)
        for identity_type, normalized_identifier in existing_identity_rows
    }
    courses = {
        course.code: course
        for course in (
            await session.scalars(
                select(EducationCourse).where(
                    EducationCourse.tenant_id == tenant_id,
                    EducationCourse.workspace_id == workspace_id,
                )
            )
        ).all()
    }
    batches = {
        batch.code: batch
        for batch in (
            await session.scalars(
                select(EducationBatch).where(
                    EducationBatch.tenant_id == tenant_id,
                    EducationBatch.workspace_id == workspace_id,
                )
            )
        ).all()
    }
    agents = {
        agent.public_id: agent
        for agent in (
            await session.scalars(
                select(Agent).where(
                    Agent.tenant_id == tenant_id,
                    Agent.workspace_id == workspace_id,
                    Agent.deleted_at.is_(None),
                )
            )
        ).all()
    }

    student_counts = Counter(row.student_number for row in rows)
    email_counts = Counter(str(row.email).lower() for row in rows if row.email is not None)
    normalized_identities: list[str | None] = []
    identity_keys: list[tuple[str, str] | None] = []
    for row in rows:
        if row.identity_type is None or row.identifier is None:
            normalized_identities.append(None)
            identity_keys.append(None)
            continue
        try:
            normalized = normalize_student_identity(row.identity_type, row.identifier)
        except ValueError:
            normalized = None
        normalized_identities.append(normalized)
        identity_keys.append(
            (row.identity_type.value, normalized) if normalized is not None else None
        )
    identity_counts = Counter(key for key in identity_keys if key is not None)

    previews: list[StudentImportRowPreview] = []
    resolved_rows: list[ResolvedStudentImportRow] = []
    purpose_cache: dict[UUID, AgentPurpose] = {}

    for index, row in enumerate(rows, start=1):
        errors: list[str] = []
        warnings: list[str] = []
        normalized_identifier = normalized_identities[index - 1]
        course_id: UUID | None = None
        batch_id: UUID | None = None
        agent_id: UUID | None = None

        if student_counts[row.student_number] > 1:
            errors.append("Student ID is duplicated inside this import")
        if row.student_number in existing_student_numbers:
            errors.append("Student ID already exists in this workspace")

        if row.email is not None:
            normalized_email = str(row.email).lower()
            if email_counts[normalized_email] > 1:
                warnings.append("Email is shared by multiple rows in this import")
            if normalized_email in existing_emails:
                warnings.append("Email is already used by another Student in this workspace")

        if row.identity_type is not None:
            if normalized_identifier is None:
                errors.append("Identity format is invalid for the selected identity type")
            else:
                identity_key = (row.identity_type.value, normalized_identifier)
                if identity_counts[identity_key] > 1:
                    errors.append("Identity is duplicated inside this import")
                if identity_key in existing_identity_keys:
                    errors.append("Identity is already linked in this workspace")
                if not row.identity_verified:
                    warnings.append(
                        "Identity will remain pending; messaging access stays blocked until it is verified"
                    )
        else:
            warnings.append("Student will be created without a channel/login identity")

        if row.course_code is not None:
            course = courses.get(row.course_code)
            if course is None:
                errors.append("Course code was not found in this workspace")
            elif course.status != CourseStatus.ACTIVE.value:
                errors.append("Course is not active")
            else:
                course_id = course.id

            batch = batches.get(row.batch_code or "")
            if batch is None:
                errors.append("Batch code was not found in this workspace")
            elif batch.status != BatchStatus.ACTIVE.value:
                errors.append("Batch is not active")
            elif course_id is not None and batch.course_id != course_id:
                errors.append("Batch does not belong to the selected Course")
            else:
                batch_id = batch.id

            agent = agents.get(row.agent_public_id or "")
            if agent is None:
                errors.append("Agent ID was not found in this workspace")
            elif agent.status not in (AgentStatus.ACTIVE, AgentStatus.DRAFT):
                errors.append("Finish training the Agent before importing enrollments")
            else:
                if agent.status == AgentStatus.DRAFT:
                    warnings.append("Agent is in draft; activate it after enrollment to enable replies")
                purpose = purpose_cache.get(agent.id)
                if purpose is None:
                    purpose = await get_agent_purpose(
                        session,
                        tenant_id=tenant_id,
                        workspace_id=workspace_id,
                        agent_id=agent.id,
                    )
                    purpose_cache[agent.id] = purpose
                if purpose is not AgentPurpose.EDUCATION:
                    errors.append("Agent must have Education purpose")
                else:
                    agent_id = agent.id

            if batch is not None:
                if row.starts_on is not None and batch.starts_on is not None:
                    if row.starts_on < batch.starts_on:
                        errors.append("Enrollment cannot start before the Batch starts")
                if row.ends_on is not None and batch.ends_on is not None:
                    if row.ends_on > batch.ends_on:
                        errors.append("Enrollment cannot end after the Batch ends")
                if row.starts_on is not None and batch.ends_on is not None:
                    if row.starts_on > batch.ends_on:
                        errors.append("Enrollment cannot start after the Batch ends")
                if row.ends_on is not None and batch.starts_on is not None:
                    if row.ends_on < batch.starts_on:
                        errors.append("Enrollment cannot end before the Batch starts")
        else:
            warnings.append("Student will be created without an Enrollment")

        valid = not errors
        previews.append(
            StudentImportRowPreview(
                row_number=index,
                valid=valid,
                errors=errors,
                warnings=warnings,
                row=row,
            )
        )
        resolved_rows.append(
            ResolvedStudentImportRow(
                row=row,
                normalized_identifier=normalized_identifier,
                course_id=course_id,
                batch_id=batch_id,
                agent_id=agent_id,
            )
        )

    valid_rows = sum(1 for preview in previews if preview.valid)
    return (
        StudentImportPreview(
            total_rows=len(previews),
            valid_rows=valid_rows,
            invalid_rows=len(previews) - valid_rows,
            rows=previews,
        ),
        resolved_rows,
    )


async def commit_student_import(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    rows: list[StudentImportRow],
) -> tuple[StudentImportPreview, StudentImportCommitResult | None]:
    preview, resolved_rows = await validate_student_import(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        rows=rows,
    )
    if preview.invalid_rows:
        return preview, None

    created_students = 0
    created_identities = 0
    created_enrollments = 0
    first_student_id: UUID | None = None
    try:
        for resolved in resolved_rows:
            row = resolved.row
            student = EducationStudent(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                student_number=row.student_number,
                name=row.name,
                email=str(row.email) if row.email is not None else None,
                custom_fields=row.custom_fields,
                status=StudentStatus.ACTIVE.value,
            )
            session.add(student)
            await session.flush()
            first_student_id = first_student_id or student.id
            created_students += 1
            enqueue_event(
                session,
                tenant_id=tenant_id,
                aggregate_type="education_student",
                aggregate_id=student.id,
                event_type="education.student.created.v1",
                payload={
                    "studentId": str(student.id),
                    "workspaceId": str(workspace_id),
                    "studentNumber": student.student_number,
                    "name": student.name,
                    "source": "bulk_import",
                },
            )

            if row.identity_type is not None and resolved.normalized_identifier is not None:
                identity_status = (
                    StudentIdentityStatus.VERIFIED.value
                    if row.identity_verified
                    else StudentIdentityStatus.PENDING.value
                )
                identity = EducationStudentIdentity(
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    student_id=student.id,
                    identity_type=row.identity_type.value,
                    identifier=resolved.normalized_identifier,
                    normalized_identifier=resolved.normalized_identifier,
                    label="Bulk import",
                    status=identity_status,
                    is_primary=True,
                    verified_at=datetime.now(UTC) if row.identity_verified else None,
                )
                session.add(identity)
                await session.flush()
                created_identities += 1
                enqueue_event(
                    session,
                    tenant_id=tenant_id,
                    aggregate_type="education_student_identity",
                    aggregate_id=identity.id,
                    event_type="education.student_identity.created.v1",
                    payload={
                        "identityId": str(identity.id),
                        "studentId": str(student.id),
                        "workspaceId": str(workspace_id),
                        "identityType": identity.identity_type,
                        "status": identity.status,
                        "isPrimary": True,
                        "source": "bulk_import",
                    },
                )
                if row.identity_verified:
                    enqueue_event(
                        session,
                        tenant_id=tenant_id,
                        aggregate_type="education_student_identity",
                        aggregate_id=identity.id,
                        event_type="education.student_identity.verified.v1",
                        payload={
                            "identityId": str(identity.id),
                            "studentId": str(student.id),
                            "workspaceId": str(workspace_id),
                            "identityType": identity.identity_type,
                            "source": "bulk_import",
                        },
                    )

            if (
                resolved.course_id is not None
                and resolved.batch_id is not None
                and resolved.agent_id is not None
            ):
                enrollment = EducationEnrollment(
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    student_id=student.id,
                    course_id=resolved.course_id,
                    batch_id=resolved.batch_id,
                    agent_id=resolved.agent_id,
                    starts_on=row.starts_on,
                    ends_on=row.ends_on,
                    status=row.enrollment_status,
                )
                session.add(enrollment)
                await session.flush()
                created_enrollments += 1
                enqueue_event(
                    session,
                    tenant_id=tenant_id,
                    aggregate_type="education_enrollment",
                    aggregate_id=enrollment.id,
                    event_type="education.enrollment.created.v1",
                    payload={
                        "enrollmentId": str(enrollment.id),
                        "workspaceId": str(workspace_id),
                        "studentId": str(student.id),
                        "courseId": str(enrollment.course_id),
                        "batchId": str(enrollment.batch_id),
                        "agentId": str(enrollment.agent_id),
                        "status": enrollment.status,
                        "source": "bulk_import",
                    },
                )

        if first_student_id is not None:
            enqueue_event(
                session,
                tenant_id=tenant_id,
                aggregate_type="education_student_import",
                aggregate_id=first_student_id,
                event_type="education.students.imported.v1",
                payload={
                    "workspaceId": str(workspace_id),
                    "createdStudents": created_students,
                    "createdIdentities": created_identities,
                    "createdEnrollments": created_enrollments,
                },
            )
        await session.flush()
    except IntegrityError as exc:
        raise StudentImportConflictError(
            "Import data changed after preview. Preview the file again before committing."
        ) from exc

    return (
        preview,
        StudentImportCommitResult(
            created_students=created_students,
            created_identities=created_identities,
            created_enrollments=created_enrollments,
        ),
    )
