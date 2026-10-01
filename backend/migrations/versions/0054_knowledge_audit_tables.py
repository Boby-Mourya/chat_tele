"""Retain the historical knowledge-audit revision without repeating 0043 DDL."""

revision = "0054_knowledge_audit_tables"
down_revision = "0053_bot_workflow_builder"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Knowledge snapshots and audits were already created by revision 0043."""


def downgrade() -> None:
    """Keep the tables owned by revision 0043 intact."""
