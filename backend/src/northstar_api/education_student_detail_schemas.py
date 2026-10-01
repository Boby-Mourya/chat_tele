from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from northstar_api.education_enrollments import EnrollmentStatus
from northstar_api.education_student_identities import StudentIdentityStatus, StudentIdentityType
from northstar_api.education_student_schemas import StudentOut
from northstar_api.models import Channel, ConversationState
from northstar_api.schemas import APIModel


class StudentDetailIdentityOut(APIModel):
    id: UUID
    identity_type: StudentIdentityType
    identifier: str
    label: str | None
    status: StudentIdentityStatus
    is_primary: bool
    verified_at: datetime | None
    created_at: datetime


class StudentDetailEnrollmentOut(APIModel):
    id: UUID
    course_id: UUID
    course_code: str
    course_name: str
    batch_id: UUID
    batch_code: str
    batch_name: str
    agent_id: UUID
    agent_public_id: str
    agent_name: str
    starts_on: date | None
    ends_on: date | None
    status: EnrollmentStatus
    access_state: str
    created_at: datetime
    updated_at: datetime


class StudentDetailConversationOut(APIModel):
    id: UUID
    public_id: str
    enrollment_id: UUID
    course_id: UUID
    batch_id: UUID
    agent_id: UUID
    agent_name: str
    channel: Channel
    state: ConversationState
    resolution: str | None
    started_at: datetime
    ended_at: datetime | None
    updated_at: datetime


class StudentDetailActivityOut(APIModel):
    id: UUID
    event_type: str
    conversation_id: UUID
    conversation_public_id: str
    enrollment_id: UUID
    course_id: UUID
    course_name: str
    batch_id: UUID
    batch_name: str
    agent_id: UUID
    agent_name: str
    resolution: str | None
    resolved_at: datetime
    actor_user_id: UUID | None
    details: dict[str, Any]
    created_at: datetime


class StudentDetailSummaryOut(APIModel):
    verified_identity_count: int
    active_access_count: int
    conversation_count: int
    activity_count: int
    last_active_at: datetime | None


class StudentDetailOut(APIModel):
    student: StudentOut
    identities: list[StudentDetailIdentityOut]
    enrollments: list[StudentDetailEnrollmentOut]
    conversations: list[StudentDetailConversationOut]
    activity: list[StudentDetailActivityOut]
    summary: StudentDetailSummaryOut
