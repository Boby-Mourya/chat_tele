from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.database import get_session
from northstar_api.dependencies import require_permissions
from northstar_api.education import EducationCourse
from northstar_api.education_activity_schemas import EducationActivityOut
from northstar_api.education_batches import EducationBatch
from northstar_api.education_student_activity import EducationStudentActivityEvent
from northstar_api.education_students import EducationStudent
from northstar_api.models import Agent, Conversation
from northstar_api.schemas import PageResult
from northstar_api.security import Principal

router = APIRouter(prefix="/education/activity", tags=["education"])
DB = Annotated[AsyncSession, Depends(get_session)]
EducationViewPrincipal = Annotated[Principal, Depends(require_permissions("education.view"))]


def _workspace_id(principal: Principal) -> UUID:
    if principal.workspace_id is None:
        raise HTTPException(status_code=403, detail="Workspace access is unavailable")
    return principal.workspace_id


@router.get("", response_model=PageResult[EducationActivityOut])
async def list_education_activity(
    principal: EducationViewPrincipal,
    session: DB,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    agent_id: UUID | None = Query(default=None),
    course_id: UUID | None = Query(default=None),
    batch_id: UUID | None = Query(default=None),
    student_id: UUID | None = Query(default=None),
    event_type: str | None = Query(default=None, min_length=1, max_length=80),
    search: str | None = Query(default=None, max_length=320),
) -> PageResult[EducationActivityOut]:
    """List append-only Education activity in the active workspace.

    Activity remains owned by the existing EducationStudentActivityEvent stream.
    This endpoint is read-only and only enriches those events for admin browsing.
    """

    workspace_id = _workspace_id(principal)
    conditions = [
        EducationStudentActivityEvent.tenant_id == principal.tenant_id,
        EducationStudentActivityEvent.workspace_id == workspace_id,
        EducationStudent.tenant_id == principal.tenant_id,
        EducationStudent.workspace_id == workspace_id,
        EducationCourse.tenant_id == principal.tenant_id,
        EducationCourse.workspace_id == workspace_id,
        EducationBatch.tenant_id == principal.tenant_id,
        EducationBatch.workspace_id == workspace_id,
        Agent.tenant_id == principal.tenant_id,
        Agent.workspace_id == workspace_id,
        Conversation.tenant_id == principal.tenant_id,
        Conversation.workspace_id == workspace_id,
    ]
    if principal.agent_ids is not None:
        conditions.append(EducationStudentActivityEvent.agent_id.in_(principal.agent_ids))
    if agent_id is not None:
        conditions.append(EducationStudentActivityEvent.agent_id == agent_id)
    if course_id is not None:
        conditions.append(EducationStudentActivityEvent.course_id == course_id)
    if batch_id is not None:
        conditions.append(EducationStudentActivityEvent.batch_id == batch_id)
    if student_id is not None:
        conditions.append(EducationStudentActivityEvent.student_id == student_id)
    if event_type and event_type.strip():
        conditions.append(EducationStudentActivityEvent.event_type == event_type.strip())
    if search and search.strip():
        pattern = f"%{search.strip()}%"
        conditions.append(
            or_(
                EducationStudent.student_number.ilike(pattern),
                EducationStudent.name.ilike(pattern),
                EducationStudent.email.ilike(pattern),
                EducationCourse.code.ilike(pattern),
                EducationCourse.name.ilike(pattern),
                EducationBatch.code.ilike(pattern),
                EducationBatch.name.ilike(pattern),
                Agent.public_id.ilike(pattern),
                Agent.name.ilike(pattern),
                Conversation.public_id.ilike(pattern),
                EducationStudentActivityEvent.event_type.ilike(pattern),
                EducationStudentActivityEvent.resolution.ilike(pattern),
            )
        )

    base = (
        select(
            EducationStudentActivityEvent,
            EducationStudent,
            EducationCourse,
            EducationBatch,
            Agent,
            Conversation,
        )
        .join(EducationStudent, EducationStudent.id == EducationStudentActivityEvent.student_id)
        .join(EducationCourse, EducationCourse.id == EducationStudentActivityEvent.course_id)
        .join(EducationBatch, EducationBatch.id == EducationStudentActivityEvent.batch_id)
        .join(Agent, Agent.id == EducationStudentActivityEvent.agent_id)
        .join(Conversation, Conversation.id == EducationStudentActivityEvent.conversation_id)
        .where(*conditions)
    )
    count_query = (
        select(func.count(EducationStudentActivityEvent.id))
        .join(EducationStudent, EducationStudent.id == EducationStudentActivityEvent.student_id)
        .join(EducationCourse, EducationCourse.id == EducationStudentActivityEvent.course_id)
        .join(EducationBatch, EducationBatch.id == EducationStudentActivityEvent.batch_id)
        .join(Agent, Agent.id == EducationStudentActivityEvent.agent_id)
        .join(Conversation, Conversation.id == EducationStudentActivityEvent.conversation_id)
        .where(*conditions)
    )
    total = int(await session.scalar(count_query) or 0)
    rows = (
        await session.execute(
            base.order_by(
                EducationStudentActivityEvent.created_at.desc(),
                EducationStudentActivityEvent.id.desc(),
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()

    items = [
        EducationActivityOut(
            id=event.id,
            event_type=event.event_type,
            student_id=student.id,
            student_number=student.student_number,
            student_name=student.name,
            student_email=student.email,
            enrollment_id=event.enrollment_id,
            course_id=course.id,
            course_code=course.code,
            course_name=course.name,
            batch_id=batch.id,
            batch_code=batch.code,
            batch_name=batch.name,
            agent_id=agent.id,
            agent_public_id=agent.public_id,
            agent_name=agent.name,
            conversation_id=conversation.id,
            conversation_public_id=conversation.public_id,
            resolution=event.resolution,
            resolved_at=event.resolved_at,
            actor_user_id=event.actor_user_id,
            details=event.details_json,
            created_at=event.created_at,
        )
        for event, student, course, batch, agent, conversation in rows
    ]
    return PageResult(items=items, total=total, page=page, page_size=page_size)
