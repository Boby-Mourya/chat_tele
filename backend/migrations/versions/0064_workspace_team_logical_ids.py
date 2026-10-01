"""Preserve logical team identifiers in the normalized team projection."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0064_workspace_team_logical_ids"
down_revision = "0063_workspace_security_policy_records"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workspace_team_records",
        sa.Column("team_id", sa.String(length=64), nullable=True),
    )
    # Existing projections were created before the logical ID was persisted.
    # Their stable database IDs are the safest deterministic backfill value.
    op.execute(
        sa.text(
            "UPDATE workspace_team_records "
            "SET team_id = CAST(id AS VARCHAR(64)) "
            "WHERE team_id IS NULL"
        )
    )
    op.alter_column("workspace_team_records", "team_id", nullable=False)
    op.create_unique_constraint(
        "uq_workspace_team_records_id",
        "workspace_team_records",
        ["workspace_id", "team_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_workspace_team_records_id", "workspace_team_records", type_="unique")
    op.drop_column("workspace_team_records", "team_id")
