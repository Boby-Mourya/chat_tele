"""Additive, workspace-scoped course publishing records.

The existing KnowledgeSource and extraction workers own uploads. These records
snapshot approved extraction versions and explicit block assignments; they never
change model configuration or attach a student ID to shared course content.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pgvector.sqlalchemy import HALFVEC
from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from northstar_api.config import get_settings
from northstar_api.database import Base

JSON_DOCUMENT = JSON().with_variant(JSONB, "postgresql")
VECTOR = JSON().with_variant(HALFVEC(get_settings().embedding_dimension), "postgresql")


class WorkspaceBoundary:
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)


class AgentBoundary(WorkspaceBoundary):
    agent_id: Mapped[UUID] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)


class Record:
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CourseCurriculum(Record, WorkspaceBoundary, Base):
    __tablename__ = "course_knowledge_curricula"
    __table_args__ = (UniqueConstraint("workspace_id", "course_id", "code", name="uq_ck_curriculum_code"),)
    course_id: Mapped[UUID] = mapped_column(
        ForeignKey("education_courses.id", ondelete="CASCADE"), index=True
    )
    code: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(160))
    teaching_configuration: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class CoursePaper(Record, WorkspaceBoundary, Base):
    __tablename__ = "course_knowledge_papers"
    __table_args__ = (UniqueConstraint("curriculum_id", "code", name="uq_ck_paper_code"),)
    curriculum_id: Mapped[UUID] = mapped_column(
        ForeignKey("course_knowledge_curricula.id", ondelete="CASCADE"), index=True
    )
    code: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(160))
    topics: Mapped[list[dict[str, str]]] = mapped_column(JSON_DOCUMENT, default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class CourseBatchCurriculum(WorkspaceBoundary, Base):
    __tablename__ = "course_knowledge_batch_curricula"
    batch_id: Mapped[UUID] = mapped_column(
        ForeignKey("education_batches.id", ondelete="CASCADE"), primary_key=True
    )
    curriculum_id: Mapped[UUID] = mapped_column(
        ForeignKey("course_knowledge_curricula.id", ondelete="RESTRICT"), index=True
    )


class CourseEnrollmentAccess(AgentBoundary, Base):
    __tablename__ = "course_knowledge_enrollment_access"
    __table_args__ = (CheckConstraint("revision >= 1", name="ck_ck_access_revision"),)
    enrollment_id: Mapped[UUID] = mapped_column(
        ForeignKey("education_enrollments.id", ondelete="CASCADE"), primary_key=True
    )
    curriculum_id: Mapped[UUID] = mapped_column(
        ForeignKey("course_knowledge_curricula.id", ondelete="RESTRICT"), index=True
    )
    paper_ids: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list)
    selected_paper_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("course_knowledge_papers.id", ondelete="RESTRICT")
    )
    revision: Mapped[int] = mapped_column(Integer, default=1)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class CourseStudySelection(Record, AgentBoundary, Base):
    __tablename__ = "course_knowledge_study_selections"
    __table_args__ = (
        UniqueConstraint("workspace_id", "agent_id", "identity_id", name="uq_ck_identity_selection"),
        CheckConstraint(
            "interaction_state IN ('awaiting_course_selection', 'awaiting_paper_selection', "
            "'awaiting_quiz_answer', 'ready_for_question')",
            name="ck_ck_selection_interaction_state",
        ),
        CheckConstraint("selection_revision >= 0", name="ck_ck_selection_revision"),
    )
    identity_id: Mapped[UUID] = mapped_column(
        ForeignKey("education_student_identities.id", ondelete="CASCADE")
    )
    enrollment_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("education_enrollments.id", ondelete="SET NULL")
    )
    menu_ids: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list)
    menu_open: Mapped[bool] = mapped_column(Boolean, default=False)
    interaction_state: Mapped[str] = mapped_column(String(40), default="ready_for_question")
    pending_question: Mapped[str | None] = mapped_column(Text)
    menu_id: Mapped[UUID | None] = mapped_column()
    menu_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    menu_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    selection_revision: Mapped[int] = mapped_column(Integer, default=0)


class CourseSourceVersion(Record, AgentBoundary, Base):
    __tablename__ = "course_knowledge_source_versions"
    __table_args__ = (
        UniqueConstraint(
            "source_id", "source_revision", "processing_hash", "record_hash", name="uq_ck_source_snapshot"
        ),
        CheckConstraint("source_revision >= 1", name="ck_ck_source_revision"),
        Index(
            "ix_ck_source_reuse",
            "tenant_id",
            "workspace_id",
            "agent_id",
            "source_checksum",
            "processing_hash",
        ),
    )
    source_id: Mapped[UUID] = mapped_column(
        ForeignKey("knowledge_sources.id", ondelete="CASCADE"), index=True
    )
    source_revision: Mapped[int] = mapped_column(Integer)
    source_checksum: Mapped[str] = mapped_column(String(64))
    processing_hash: Mapped[str] = mapped_column(String(64))
    record_hash: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(240))
    original_object_key: Mapped[str | None] = mapped_column(Text)
    extraction_key: Mapped[str | None] = mapped_column(Text)
    record: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT)
    validation: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT)
    withdrawn: Mapped[bool] = mapped_column(Boolean, default=False)


class CourseUploadIntent(Record, AgentBoundary, Base):
    __tablename__ = "course_knowledge_upload_intents"
    __table_args__ = (
        UniqueConstraint("workspace_id", "agent_id", "idempotency_key", name="uq_ck_upload_request"),
    )
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    source_id: Mapped[UUID] = mapped_column(
        ForeignKey("knowledge_sources.id", ondelete="CASCADE"), index=True
    )
    destination: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT)
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))


class CourseMaterialAssignment(Record, AgentBoundary, Base):
    __tablename__ = "course_knowledge_assignments"
    __table_args__ = (
        UniqueConstraint("workspace_id", "agent_id", "idempotency_key", name="uq_ck_assignment_request"),
        CheckConstraint("revision >= 1", name="ck_ck_assignment_revision"),
        CheckConstraint(
            "(overview = true AND paper_id IS NULL) OR (overview = false AND paper_id IS NOT NULL)",
            name="ck_ck_assignment_paper",
        ),
        CheckConstraint("status IN ('review', 'approved', 'withdrawn')", name="ck_ck_assignment_status"),
        Index(
            "ix_ck_assignment_audience",
            "tenant_id",
            "workspace_id",
            "agent_id",
            "course_id",
            "curriculum_id",
            "paper_id",
            "batch_id",
        ),
    )
    idempotency_key: Mapped[str] = mapped_column(String(128))
    index_status: Mapped[str] = mapped_column(String(20), default="not_prepared")
    index_error: Mapped[str | None] = mapped_column(String(500))
    source_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("course_knowledge_source_versions.id", ondelete="CASCADE"), index=True
    )
    course_id: Mapped[UUID] = mapped_column(ForeignKey("education_courses.id", ondelete="RESTRICT"))
    curriculum_id: Mapped[UUID] = mapped_column(
        ForeignKey("course_knowledge_curricula.id", ondelete="RESTRICT")
    )
    paper_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("course_knowledge_papers.id", ondelete="RESTRICT")
    )
    batch_id: Mapped[UUID | None] = mapped_column(ForeignKey("education_batches.id", ondelete="RESTRICT"))
    overview: Mapped[bool] = mapped_column(Boolean, default=False)
    block_ids: Mapped[list[str]] = mapped_column(JSON_DOCUMENT)
    topic_ids: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list)
    material_type: Mapped[str] = mapped_column(String(40), default="notes")
    language: Mapped[str] = mapped_column(String(80), default="English")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(20), default="review")
    approval_fingerprint: Mapped[str | None] = mapped_column(String(64))
    approved_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_reason: Mapped[str] = mapped_column(Text, default="")
    validation: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict)


class CourseIndexEntry(Record, AgentBoundary, Base):
    __tablename__ = "course_knowledge_index_entries"
    __table_args__ = (
        UniqueConstraint("assignment_id", "assignment_revision", "ordinal", name="uq_ck_index_stage"),
    )
    assignment_id: Mapped[UUID] = mapped_column(
        ForeignKey("course_knowledge_assignments.id", ondelete="CASCADE"), index=True
    )
    assignment_revision: Mapped[int] = mapped_column(Integer)
    approval_fingerprint: Mapped[str] = mapped_column(String(64))
    ordinal: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    block_ids: Mapped[list[str]] = mapped_column(JSON_DOCUMENT)
    source_references: Mapped[list[dict[str, Any]]] = mapped_column(JSON_DOCUMENT)
    embedding: Mapped[list[float]] = mapped_column(VECTOR)
    embedding_model: Mapped[str] = mapped_column(String(240))


class CourseKnowledgeRelease(Record, AgentBoundary, Base):
    __tablename__ = "course_knowledge_releases"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "agent_id",
            "course_id",
            "curriculum_id",
            "manifest_hash",
            name="uq_ck_release_manifest",
        ),
        CheckConstraint("status IN ('candidate', 'published', 'failed')", name="ck_ck_release_status"),
    )
    course_id: Mapped[UUID] = mapped_column(ForeignKey("education_courses.id", ondelete="RESTRICT"))
    curriculum_id: Mapped[UUID] = mapped_column(
        ForeignKey("course_knowledge_curricula.id", ondelete="RESTRICT")
    )
    manifest: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT)
    manifest_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="candidate")
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CourseReleaseMember(AgentBoundary, Base):
    __tablename__ = "course_knowledge_release_members"
    release_id: Mapped[UUID] = mapped_column(
        ForeignKey("course_knowledge_releases.id", ondelete="CASCADE"), primary_key=True
    )
    assignment_id: Mapped[UUID] = mapped_column(
        ForeignKey("course_knowledge_assignments.id", ondelete="CASCADE"), primary_key=True
    )
    assignment_revision: Mapped[int] = mapped_column(Integer)
    approval_fingerprint: Mapped[str] = mapped_column(String(64))


class CourseReleaseHead(Record, AgentBoundary, Base):
    __tablename__ = "course_knowledge_release_heads"
    __table_args__ = (
        UniqueConstraint("workspace_id", "agent_id", "course_id", "curriculum_id", name="uq_ck_release_head"),
    )
    course_id: Mapped[UUID] = mapped_column(ForeignKey("education_courses.id", ondelete="RESTRICT"))
    curriculum_id: Mapped[UUID] = mapped_column(
        ForeignKey("course_knowledge_curricula.id", ondelete="RESTRICT")
    )
    release_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("course_knowledge_releases.id", ondelete="RESTRICT")
    )
    epoch: Mapped[int] = mapped_column(Integer, default=0)


class CourseDerivedArtifact(Record, AgentBoundary, Base):
    __tablename__ = "course_knowledge_derived_artifacts"
    assignment_ids: Mapped[list[str]] = mapped_column(JSON_DOCUMENT)
    source_fingerprints: Mapped[dict[str, str]] = mapped_column(JSON_DOCUMENT)
    source_version_ids: Mapped[list[str]] = mapped_column(JSON_DOCUMENT)
    source_block_ids: Mapped[list[str]] = mapped_column(JSON_DOCUMENT)
    audience: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT)
    artifact_type: Mapped[str] = mapped_column(String(40))
    content: Mapped[str] = mapped_column(Text)
    generation_configuration_version: Mapped[str] = mapped_column(String(64))
    review_status: Mapped[str] = mapped_column(String(20), default="review")
    approved_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    review_reason: Mapped[str] = mapped_column(Text, default="")
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    answer_key_validated: Mapped[bool] = mapped_column(Boolean, default=False)
    withdrawn: Mapped[bool] = mapped_column(Boolean, default=False)


class CourseResponseContext(AgentBoundary, Base):
    __tablename__ = "course_knowledge_response_contexts"
    message_id: Mapped[UUID] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), primary_key=True)
    enrollment_id: Mapped[UUID] = mapped_column(
        ForeignKey("education_enrollments.id", ondelete="CASCADE"), index=True
    )
    context_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    citations: Mapped[list[dict[str, Any]]] = mapped_column(JSON_DOCUMENT, default=list)


class CourseAcademicReview(Record, AgentBoundary, Base):
    __tablename__ = "course_knowledge_academic_reviews"
    __table_args__ = (
        UniqueConstraint("message_id", name="uq_ck_academic_review_message"),
        CheckConstraint(
            "status IN ('pending', 'open', 'assigned', 'corrected', 'confirmed', 'closed')",
            name="ck_ck_academic_review_status",
        ),
        CheckConstraint(
            "correction_delivery_status IN ('not_requested', 'requested', 'sent', 'failed')",
            name="ck_ck_review_delivery_status",
        ),
    )
    message_id: Mapped[UUID] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"))
    enrollment_id: Mapped[UUID] = mapped_column(ForeignKey("education_enrollments.id", ondelete="CASCADE"))
    question: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    student_id: Mapped[UUID | None] = mapped_column(ForeignKey("education_students.id", ondelete="CASCADE"))
    course_id: Mapped[UUID | None] = mapped_column(ForeignKey("education_courses.id", ondelete="RESTRICT"))
    curriculum_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("course_knowledge_curricula.id", ondelete="RESTRICT")
    )
    paper_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("course_knowledge_papers.id", ondelete="SET NULL")
    )
    batch_id: Mapped[UUID | None] = mapped_column(ForeignKey("education_batches.id", ondelete="RESTRICT"))
    answer: Mapped[str] = mapped_column(Text, default="")
    internal_evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSON_DOCUMENT, default=list)
    external_evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSON_DOCUMENT, default=list)
    assigned_reviewer: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    resolution: Mapped[str | None] = mapped_column(Text)
    correction_delivery_status: Mapped[str] = mapped_column(String(30), default="not_requested")
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CoursePracticeAttempt(Record, AgentBoundary, Base):
    __tablename__ = "course_knowledge_practice_attempts"
    __table_args__ = (
        UniqueConstraint("workspace_id", "agent_id", "idempotency_key", name="uq_ck_practice_idempotency"),
        CheckConstraint("status IN ('open', 'answered')", name="ck_ck_practice_status"),
    )
    student_id: Mapped[UUID] = mapped_column(ForeignKey("education_students.id", ondelete="CASCADE"))
    enrollment_id: Mapped[UUID] = mapped_column(ForeignKey("education_enrollments.id", ondelete="CASCADE"))
    paper_id: Mapped[UUID] = mapped_column(ForeignKey("course_knowledge_papers.id", ondelete="RESTRICT"))
    conversation_id: Mapped[UUID | None] = mapped_column(ForeignKey("conversations.id", ondelete="SET NULL"))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    question: Mapped[str] = mapped_column(Text)
    answer_key: Mapped[str] = mapped_column(Text)
    student_answer: Mapped[str | None] = mapped_column(Text)
    is_correct: Mapped[bool | None] = mapped_column(Boolean)
    feedback: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="open")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CoursePaperProgress(Record, AgentBoundary, Base):
    __tablename__ = "course_knowledge_progress"
    __table_args__ = (
        UniqueConstraint("enrollment_id", "paper_id", name="uq_ck_progress_enrollment_paper"),
        CheckConstraint(
            "learning_status IN ('not_started', 'practicing', 'review_needed')", name="ck_ck_learning_status"
        ),
    )
    student_id: Mapped[UUID] = mapped_column(ForeignKey("education_students.id", ondelete="CASCADE"))
    enrollment_id: Mapped[UUID] = mapped_column(ForeignKey("education_enrollments.id", ondelete="CASCADE"))
    paper_id: Mapped[UUID] = mapped_column(ForeignKey("course_knowledge_papers.id", ondelete="RESTRICT"))
    questions_asked: Mapped[int] = mapped_column(Integer, default=0)
    practice_attempts: Mapped[int] = mapped_column(Integer, default=0)
    objective_answers_correct: Mapped[int] = mapped_column(Integer, default=0)
    objective_answers_graded: Mapped[int] = mapped_column(Integer, default=0)
    learning_status: Mapped[str] = mapped_column(String(20), default="not_started")
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
