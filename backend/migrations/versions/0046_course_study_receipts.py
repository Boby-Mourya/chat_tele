"""Durable WhatsApp course-menu replies with live selection fingerprints."""
import sqlalchemy as sa
from alembic import op

revision = "0046_course_study_receipts"
down_revision = "0045_course_knowledge_releases"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("course_knowledge_study_receipts",
        sa.Column("receipt_id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_id", sa.Uuid(), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("identity_id", sa.Uuid(), sa.ForeignKey("education_student_identities.id", ondelete="SET NULL")),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("scope_fingerprint", sa.String(64), nullable=False),
        sa.Column("sent_ids", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    for field in ("tenant_id", "workspace_id", "agent_id"):
        op.create_index(f"ix_course_knowledge_study_receipts_{field}", "course_knowledge_study_receipts", [field])
    if op.get_bind().dialect.name == "postgresql":
        op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON course_knowledge_study_receipts TO northstar_app")
        op.execute("ALTER TABLE course_knowledge_study_receipts ENABLE ROW LEVEL SECURITY")
        op.execute("CREATE POLICY tenant_isolation ON course_knowledge_study_receipts "
            "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
            "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)")


def downgrade():
    op.drop_table("course_knowledge_study_receipts")
