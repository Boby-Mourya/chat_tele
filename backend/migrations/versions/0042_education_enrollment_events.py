"""Idempotent CRM/LMS enrollment receipts."""

import sqlalchemy as sa
from alembic import op

revision = "0042_education_enrollment_events"
down_revision = "0041_conversation_visitor_details"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "education_enrollment_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("agent_id", sa.Uuid(), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source", sa.String(60), nullable=False),
        sa.Column("event_id", sa.String(160), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("student_id", sa.Uuid(), sa.ForeignKey("education_students.id"), nullable=False),
        sa.Column("enrollment_id", sa.Uuid(), sa.ForeignKey("education_enrollments.id"), nullable=False),
        sa.Column("lead_id", sa.Uuid(), sa.ForeignKey("leads.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "workspace_id", "agent_id", "source", "event_id", name="uq_education_enrollment_event"
        ),
    )
    for field in ("tenant_id", "workspace_id"):
        op.create_index(f"ix_education_enrollment_events_{field}", "education_enrollment_events", [field])
    if op.get_bind().dialect.name == "postgresql":
        op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON education_enrollment_events TO northstar_app")
        op.execute("ALTER TABLE education_enrollment_events ENABLE ROW LEVEL SECURITY")
        op.execute(
            "CREATE POLICY tenant_isolation ON education_enrollment_events "
            "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
            "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
        )


def downgrade():
    op.drop_table("education_enrollment_events")
