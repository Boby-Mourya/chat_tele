from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.education_curricula import CurriculumStatus, EducationCurriculum


async def ensure_default_curriculum(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    course_id: UUID,
) -> EducationCurriculum:
    curriculum = await session.scalar(
        select(EducationCurriculum)
        .where(
            EducationCurriculum.tenant_id == tenant_id,
            EducationCurriculum.workspace_id == workspace_id,
            EducationCurriculum.course_id == course_id,
            EducationCurriculum.status == CurriculumStatus.ACTIVE.value,
        )
        .order_by(EducationCurriculum.created_at)
        .limit(1)
    )
    if curriculum is not None:
        return curriculum
    curriculum = EducationCurriculum(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        course_id=course_id,
        version="LEGACY",
        name="Legacy syllabus",
        description="Automatically created for backward-compatible course setup.",
        status=CurriculumStatus.ACTIVE.value,
    )
    session.add(curriculum)
    await session.flush()
    return curriculum
