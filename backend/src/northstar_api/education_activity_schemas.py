from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from northstar_api.schemas import APIModel


class EducationActivityOut(APIModel):
    id: UUID
    event_type: str
    student_id: UUID
    student_number: str
    student_name: str
    student_email: str | None
    enrollment_id: UUID
    course_id: UUID
    course_code: str
    course_name: str
    batch_id: UUID
    batch_code: str
    batch_name: str
    agent_id: UUID
    agent_public_id: str
    agent_name: str
    conversation_id: UUID
    conversation_public_id: str
    resolution: str | None
    resolved_at: datetime
    actor_user_id: UUID | None
    details: dict[str, Any]
    created_at: datetime
