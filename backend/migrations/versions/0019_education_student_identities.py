"""Add workspace-scoped Education student identities.

Revision ID: 0019_education_student_identities
Revises: 0018_education_students
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0019_education_student_identities"
down_revision = "0018_education_students"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "education_student_identities" in tables:
        return

    op.create_table(
        "education_student_identities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("identity_type", sa.String(length=32), nullable=False),
        sa.Column("identifier", sa.String(length=320), nullable=False),
        sa.Column("normalized_identifier", sa.String(length=320), nullable=False),
        sa.Column("label", sa.String(length=80), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "identity_type IN ('whatsapp', 'telegram', 'website_login', 'alternate_phone')",
            name="ck_education_student_identities_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'verified', 'revoked')",
            name="ck_education_student_identities_status",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["student_id"], ["education_students.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "identity_type",
            "normalized_identifier",
            name="uq_education_student_identities_workspace_identity",
        ),
    )
    op.create_index(
        "ix_education_student_identities_tenant_id",
        "education_student_identities",
        ["tenant_id"],
    )
    op.create_index(
        "ix_education_student_identities_workspace_id",
        "education_student_identities",
        ["workspace_id"],
    )
    op.create_index(
        "ix_education_student_identities_student_id",
        "education_student_identities",
        ["student_id"],
    )
    op.create_index(
        "ix_education_student_identities_scope",
        "education_student_identities",
        ["tenant_id", "workspace_id", "identity_type", "status"],
    )
    op.create_index(
        "ix_education_student_identities_student",
        "education_student_identities",
        ["student_id", "status"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    if "education_student_identities" in set(sa.inspect(bind).get_table_names()):
        op.drop_table("education_student_identities")
