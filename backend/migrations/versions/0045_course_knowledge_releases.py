"""Versioned course assignments, releases, selections and durable index stages.

Schema definitions are frozen here: no imports of mutable application models.
Existing sources, enrollments, provider settings and published agents are not
rewritten. Legacy Education material remains an admin inbox until approved.
"""
from __future__ import annotations

import os

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import HALFVEC
from sqlalchemy.dialects.postgresql import JSONB

revision = "0045_course_knowledge_releases"
down_revision = "0044_hybrid_extraction_review"
branch_labels = None
depends_on = None

PREFIX = "course_knowledge_"
JSON = sa.JSON().with_variant(JSONB(), "postgresql")


def fk(name, target, *, nullable=False, primary=False, ondelete="RESTRICT"):
    return sa.Column(name, sa.Uuid(), sa.ForeignKey(target, ondelete=ondelete), nullable=nullable, primary_key=primary)


def value(name, kind, *, nullable=False, default=None):
    return sa.Column(name, kind, nullable=nullable, server_default=default)


def create(name, columns, constraints=(), *, agent=True, record=True):
    table = PREFIX + name
    common = [fk("tenant_id", "tenants.id", ondelete="CASCADE"), fk("workspace_id", "workspaces.id", ondelete="CASCADE")]
    if agent:
        common.append(fk("agent_id", "agents.id", ondelete="CASCADE"))
    if record:
        common = [sa.Column("id", sa.Uuid(), primary_key=True), value("created_at", sa.DateTime(timezone=True), default=sa.func.now())] + common
    op.create_table(table, *common, *columns, *constraints)
    for field in ("tenant_id", "workspace_id", "agent_id") if agent else ("tenant_id", "workspace_id"):
        op.create_index(f"ix_{table}_{field}", table, [field])
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO northstar_app")
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {table} USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)")


def upgrade():
    create("curricula", [fk("course_id", "education_courses.id", ondelete="CASCADE"), value("code", sa.String(80)), value("name", sa.String(160)), value("teaching_configuration", JSON), value("active", sa.Boolean())], [sa.UniqueConstraint("workspace_id", "course_id", "code", name="uq_ck_curriculum_code")], agent=False)
    create("papers", [fk("curriculum_id", PREFIX + "curricula.id", ondelete="CASCADE"), value("code", sa.String(80)), value("name", sa.String(160)), value("topics", JSON), value("active", sa.Boolean())], [sa.UniqueConstraint("curriculum_id", "code", name="uq_ck_paper_code")], agent=False)
    create("batch_curricula", [fk("batch_id", "education_batches.id", primary=True, ondelete="CASCADE"), fk("curriculum_id", PREFIX + "curricula.id")], agent=False, record=False)
    create("enrollment_access", [fk("enrollment_id", "education_enrollments.id", primary=True, ondelete="CASCADE"), fk("curriculum_id", PREFIX + "curricula.id"), value("paper_ids", JSON), fk("selected_paper_id", PREFIX + "papers.id", nullable=True), value("revision", sa.Integer()), value("active", sa.Boolean())], [sa.CheckConstraint("revision >= 1", name="ck_ck_access_revision")], record=False)
    create("study_selections", [fk("identity_id", "education_student_identities.id", ondelete="CASCADE"), fk("enrollment_id", "education_enrollments.id", nullable=True, ondelete="SET NULL"), value("menu_ids", JSON), value("menu_open", sa.Boolean())], [sa.UniqueConstraint("workspace_id", "agent_id", "identity_id", name="uq_ck_identity_selection")])
    create("source_versions", [fk("source_id", "knowledge_sources.id", ondelete="CASCADE"), value("source_revision", sa.Integer()), value("source_checksum", sa.String(64)), value("processing_hash", sa.String(64)), value("record_hash", sa.String(64)), value("title", sa.String(240)), value("original_object_key", sa.Text(), nullable=True), value("extraction_key", sa.Text(), nullable=True), value("record", JSON), value("validation", JSON), value("withdrawn", sa.Boolean())], [sa.UniqueConstraint("source_id", "source_revision", "processing_hash", "record_hash", name="uq_ck_source_snapshot"), sa.CheckConstraint("source_revision >= 1", name="ck_ck_source_revision")])
    create("upload_intents", [value("idempotency_key", sa.String(128)), value("request_fingerprint", sa.String(64)), fk("source_id", "knowledge_sources.id", ondelete="CASCADE"), value("destination", JSON), fk("created_by", "users.id")], [sa.UniqueConstraint("workspace_id", "agent_id", "idempotency_key", name="uq_ck_upload_request")])
    create("assignments", [value("idempotency_key", sa.String(128)), value("index_status", sa.String(20)), value("index_error", sa.String(500), nullable=True), fk("source_version_id", PREFIX + "source_versions.id", ondelete="CASCADE"), fk("course_id", "education_courses.id"), fk("curriculum_id", PREFIX + "curricula.id"), fk("paper_id", PREFIX + "papers.id", nullable=True), fk("batch_id", "education_batches.id", nullable=True), value("overview", sa.Boolean()), value("block_ids", JSON), value("topic_ids", JSON), value("material_type", sa.String(40)), value("language", sa.String(80)), value("revision", sa.Integer()), value("status", sa.String(20)), value("approval_fingerprint", sa.String(64), nullable=True), fk("approved_by", "users.id", nullable=True), value("approved_at", sa.DateTime(timezone=True), nullable=True), value("review_reason", sa.Text()), value("validation", JSON)], [sa.UniqueConstraint("workspace_id", "agent_id", "idempotency_key", name="uq_ck_assignment_request"), sa.CheckConstraint("revision >= 1", name="ck_ck_assignment_revision"), sa.CheckConstraint("(overview = true AND paper_id IS NULL) OR (overview = false AND paper_id IS NOT NULL)", name="ck_ck_assignment_paper"), sa.CheckConstraint("status IN ('review', 'approved', 'withdrawn')", name="ck_ck_assignment_status")])
    vector = sa.JSON().with_variant(HALFVEC(int(os.environ.get("EMBEDDING_DIMENSION", "2048"))), "postgresql")
    create("index_entries", [fk("assignment_id", PREFIX + "assignments.id", ondelete="CASCADE"), value("assignment_revision", sa.Integer()), value("approval_fingerprint", sa.String(64)), value("ordinal", sa.Integer()), value("content", sa.Text()), value("content_hash", sa.String(64)), value("block_ids", JSON), value("source_references", JSON), value("embedding", vector), value("embedding_model", sa.String(240))], [sa.UniqueConstraint("assignment_id", "assignment_revision", "ordinal", name="uq_ck_index_stage")])
    create("releases", [fk("course_id", "education_courses.id"), fk("curriculum_id", PREFIX + "curricula.id"), value("manifest", JSON), value("manifest_hash", sa.String(64)), value("status", sa.String(20)), fk("created_by", "users.id"), value("published_at", sa.DateTime(timezone=True), nullable=True)], [sa.UniqueConstraint("workspace_id", "agent_id", "course_id", "curriculum_id", "manifest_hash", name="uq_ck_release_manifest"), sa.CheckConstraint("status IN ('candidate', 'published', 'failed')", name="ck_ck_release_status")])
    create("release_members", [fk("release_id", PREFIX + "releases.id", primary=True, ondelete="CASCADE"), fk("assignment_id", PREFIX + "assignments.id", primary=True, ondelete="CASCADE"), value("assignment_revision", sa.Integer()), value("approval_fingerprint", sa.String(64))], record=False)
    create("release_heads", [fk("course_id", "education_courses.id"), fk("curriculum_id", PREFIX + "curricula.id"), fk("release_id", PREFIX + "releases.id", nullable=True), value("epoch", sa.Integer())], [sa.UniqueConstraint("workspace_id", "agent_id", "course_id", "curriculum_id", name="uq_ck_release_head")])
    create("derived_artifacts", [value("assignment_ids", JSON), value("source_fingerprints", JSON), value("source_version_ids", JSON), value("source_block_ids", JSON), value("audience", JSON), value("artifact_type", sa.String(40)), value("content", sa.Text()), value("generation_configuration_version", sa.String(64)), value("review_status", sa.String(20)), fk("approved_by", "users.id", nullable=True), value("review_reason", sa.Text()), value("reviewed_at", sa.DateTime(timezone=True), nullable=True), value("answer_key_validated", sa.Boolean()), value("withdrawn", sa.Boolean())])
    create("response_contexts", [fk("message_id", "messages.id", primary=True, ondelete="CASCADE"), fk("enrollment_id", "education_enrollments.id", ondelete="CASCADE"), value("context_fingerprint", sa.String(64)), value("citations", JSON)], record=False)
    create("academic_reviews", [fk("message_id", "messages.id", ondelete="CASCADE"), fk("enrollment_id", "education_enrollments.id", ondelete="CASCADE"), value("question", sa.Text()), value("reason", sa.String(80)), value("status", sa.String(20))], [sa.UniqueConstraint("message_id", name="uq_ck_academic_review_message")])
    create("index_dispatch", [fk("assignment_id", PREFIX + "assignments.id", primary=True, ondelete="CASCADE"), sa.Column("revision", sa.Integer(), primary_key=True), value("attempts", sa.Integer()), value("next_dispatch_at", sa.DateTime(timezone=True), nullable=True), value("last_error", sa.String(200), nullable=True)], record=False)
    for name, fields in {
        "ix_ck_source_reuse": ("source_versions", ["tenant_id", "workspace_id", "agent_id", "source_checksum", "processing_hash"]),
        "ix_ck_assignment_audience": ("assignments", ["tenant_id", "workspace_id", "agent_id", "course_id", "curriculum_id", "paper_id", "batch_id"]),
    }.items():
        op.create_index(name, PREFIX + fields[0], fields[1])
    for table, fields in {
        "curricula": ["course_id"], "papers": ["curriculum_id"], "batch_curricula": ["curriculum_id"],
        "enrollment_access": ["curriculum_id"], "source_versions": ["source_id"], "upload_intents": ["source_id"],
        "assignments": ["source_version_id"], "index_entries": ["assignment_id"], "response_contexts": ["enrollment_id", "context_fingerprint"],
    }.items():
        for field in fields:
            op.create_index(f"ix_{PREFIX}{table}_{field}", PREFIX + table, [field])
    if op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE INDEX ix_ck_entries_fts ON course_knowledge_index_entries USING gin (to_tsvector('simple', content))")
        op.execute("CREATE INDEX ix_ck_entries_vector ON course_knowledge_index_entries USING hnsw (embedding halfvec_cosine_ops)")


def downgrade():
    for name in ("index_dispatch", "academic_reviews", "response_contexts", "derived_artifacts", "release_heads", "release_members", "releases", "index_entries", "assignments", "upload_intents", "source_versions", "study_selections", "enrollment_access", "batch_curricula", "papers", "curricula"):
        op.drop_table(PREFIX + name)
