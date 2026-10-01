from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from northstar_api.database import Base


class EducationKnowledgeScope(Base):
    """Bind Agent knowledge to one explicit course/curriculum/paper/batch tuple.

    A row targets exactly one source or standalone fact. Whole-source grants use
    an empty selected_block_ids list; mixed material lists stable extraction
    blocks and is checked again before evidence enters model context.
    """

    __tablename__ = "education_knowledge_scopes"
    __table_args__ = (
        CheckConstraint(
            "(source_id IS NOT NULL AND fact_id IS NULL) OR "
            "(source_id IS NULL AND fact_id IS NOT NULL)",
            name="ck_education_knowledge_scope_target",
        ),
        CheckConstraint(
            "approval_status IN ('draft', 'approved', 'published', 'withdrawn')",
            name="ck_education_knowledge_scope_approval_status",
        ),
        UniqueConstraint(
            "source_id",
            "course_id",
            "curriculum_id",
            "paper_id",
            "batch_id",
            name="uq_education_knowledge_scope_source",
        ),
        UniqueConstraint(
            "fact_id",
            "course_id",
            "curriculum_id",
            "paper_id",
            "batch_id",
            name="uq_education_knowledge_scope_fact",
        ),
        Index(
            "ix_education_knowledge_scope_lookup",
            "tenant_id",
            "workspace_id",
            "agent_id",
            "course_id",
            "batch_id",
        ),
        Index("ix_education_knowledge_scope_source_id", "source_id"),
        Index("ix_education_knowledge_scope_fact_id", "fact_id"),
        Index(
            "ix_education_knowledge_scope_publication",
            "tenant_id",
            "workspace_id",
            "agent_id",
            "approval_status",
            "withdrawn_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=False
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("knowledge_sources.id", ondelete="CASCADE"), nullable=True
    )
    source_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("education_source_versions.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    fact_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("knowledge_facts.id", ondelete="CASCADE"), nullable=True
    )
    course_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("education_courses.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    curriculum_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("education_curricula.id", ondelete="RESTRICT"), index=True, nullable=True
    )
    paper_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("education_papers.id", ondelete="RESTRICT"), index=True, nullable=True
    )
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("education_batches.id", ondelete="RESTRICT"), index=True, nullable=True
    )
    # Empty means the complete source/fact.  Non-empty IDs are stable extraction
    # block identifiers and are the access-control boundary for mixed material.
    selected_block_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    topic_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    material_type: Mapped[str] = mapped_column(String(40), default="notes", nullable=False)
    extraction_revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    mapping_revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    assignment_revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    requires_release: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    approval_status: Mapped[str] = mapped_column(String(20), default="published", nullable=False)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
