from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from northstar_api.database import Base


class EducationSourceVersion(Base):
    __tablename__ = "education_source_versions"
    __table_args__ = (UniqueConstraint("source_id", "version", name="uq_education_source_version"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("knowledge_sources.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    processing_configuration: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    state: Mapped[str] = mapped_column(String(30), default="uploaded", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EducationExtractedBlock(Base):
    __tablename__ = "education_extracted_blocks"
    __table_args__ = (
        UniqueConstraint("source_version_id", "block_id", name="uq_education_extracted_block"),
        Index("ix_education_extracted_block_order", "source_version_id", "ordinal"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    source_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("education_source_versions.id", ondelete="CASCADE"), index=True)
    block_id: Mapped[str] = mapped_column(String(120), nullable=False)
    parent_block_id: Mapped[str | None] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    extraction_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EducationValidationReport(Base):
    __tablename__ = "education_validation_reports"
    __table_args__ = (
        UniqueConstraint(
            "source_version_id", "extraction_revision", "mapping_revision",
            name="uq_education_validation_report_revision",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    source_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("education_source_versions.id", ondelete="CASCADE"), index=True)
    extraction_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    mapping_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    checks: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    issues: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    critical_issues_resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EducationKnowledgeRelease(Base):
    __tablename__ = "education_knowledge_releases"
    __table_args__ = (
        UniqueConstraint("agent_id", "course_id", "curriculum_id", "revision", name="uq_education_release_revision"),
        Index("ix_education_release_active", "tenant_id", "workspace_id", "agent_id", "course_id", "curriculum_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("education_courses.id", ondelete="RESTRICT"), index=True)
    curriculum_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("education_curricula.id", ondelete="RESTRICT"), index=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="candidate", index=True)
    manifest: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    index_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    activated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EducationReleaseAssignment(Base):
    __tablename__ = "education_release_assignments"
    __table_args__ = (UniqueConstraint("release_id", "assignment_id", name="uq_education_release_assignment"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    release_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("education_knowledge_releases.id", ondelete="CASCADE"), index=True)
    assignment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("education_knowledge_scopes.id", ondelete="RESTRICT"), index=True)
    assignment_revision: Mapped[int] = mapped_column(Integer, nullable=False)


class EducationDerivedLearningArtifact(Base):
    __tablename__ = "education_derived_learning_artifacts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    artifact_type: Mapped[str] = mapped_column(String(30), nullable=False)
    content: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source_version_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    source_block_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    course_assignment_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    generation_configuration_version: Mapped[str] = mapped_column(String(80), nullable=False)
    review_status: Mapped[str] = mapped_column(String(20), default="unreviewed")
    publication_status: Mapped[str] = mapped_column(String(20), default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
