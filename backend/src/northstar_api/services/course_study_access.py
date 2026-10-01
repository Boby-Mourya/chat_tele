"""Add explicit course/paper selection after the existing identity checks."""

from __future__ import annotations

from dataclasses import replace

from sqlalchemy import select

from northstar_api.config import get_settings
from northstar_api.course_knowledge_models import CourseStudySelection
from northstar_api.education_enrollments import EducationEnrollment
from northstar_api.services.course_knowledge import Boundary
from northstar_api.services.course_knowledge_selection import resolve_study_selection
from northstar_api.services.education_runtime_authorization import (
    EducationAccessReason,
    _active_enrollment_denial_reason,
    authorize_education_access,
)
from northstar_api.services.workspace_dates import workspace_today


async def authorize_study_access(session, *, tenant_id, workspace_id, agent, identity, message):
    decision = await authorize_education_access(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        agent=agent,
        identity=identity,
        message=message,
    )
    if not get_settings().education_multi_course_enabled:
        return replace(decision, authorized=False, reason=EducationAccessReason.FEATURE_DISABLED), None
    if not decision.authorized and decision.reason is not EducationAccessReason.ENROLLMENT_AMBIGUOUS:
        if decision.identity_id is not None:
            state = await session.scalar(
                select(CourseStudySelection).where(
                    CourseStudySelection.tenant_id == tenant_id,
                    CourseStudySelection.workspace_id == workspace_id,
                    CourseStudySelection.agent_id == agent.id,
                    CourseStudySelection.identity_id == decision.identity_id,
                )
            )
            if state:
                state.enrollment_id = None
                state.menu_ids = []
                state.menu_open = False
        return decision, None
    if decision.identity_id is None or decision.student_id is None:
        return replace(decision, authorized=False), None
    rows = (
        await session.scalars(
            select(EducationEnrollment).where(
                EducationEnrollment.tenant_id == tenant_id,
                EducationEnrollment.workspace_id == workspace_id,
                EducationEnrollment.agent_id == agent.id,
                EducationEnrollment.student_id == decision.student_id,
                EducationEnrollment.status == "active",
            )
        )
    ).all()
    today = await workspace_today(session, tenant_id=tenant_id, workspace_id=workspace_id)
    valid = []
    for row in rows:
        if (
            await _active_enrollment_denial_reason(
                session, tenant_id=tenant_id, workspace_id=workspace_id, enrollment=row, as_of=today
            )
            is None
        ):
            valid.append(row)
    choice = await resolve_study_selection(
        session, Boundary(tenant_id, workspace_id, agent.id), decision.identity_id, valid, message
    )
    if choice.enrollment is None:
        return replace(
            decision, authorized=False, reason=EducationAccessReason.ENROLLMENT_AMBIGUOUS
        ), choice.prompt
    selected = choice.enrollment
    return replace(
        decision,
        authorized=True,
        reason=EducationAccessReason.AUTHORIZED,
        enrollment_id=selected.id,
        course_id=selected.course_id,
        batch_id=selected.batch_id,
    ), choice.prompt
