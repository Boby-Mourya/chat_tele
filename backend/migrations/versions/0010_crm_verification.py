"""Separate CRM acknowledgement from retryable read-back verification.

Revision ID: 0010_crm_verification
Revises: 0009_integration_audit
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010_crm_verification"
down_revision = "0009_integration_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for name in ("retry_cycle_attempts", "verification_attempt_count", "verification_cycle_attempts"):
        op.add_column("crm_deliveries", sa.Column(name, sa.Integer(), nullable=False, server_default="0"))
    for name in ("payload_json", "verification_evidence_json"):
        op.add_column(
            "crm_deliveries", sa.Column(name, sa.JSON(), nullable=False, server_default=sa.text("'{}'"))
        )
    op.add_column(
        "crm_deliveries",
        sa.Column("verification_status", sa.String(40), nullable=False, server_default="pending"),
    )
    op.add_column("crm_deliveries", sa.Column("next_verification_at", sa.DateTime(timezone=True)))
    op.add_column("crm_deliveries", sa.Column("verification_error_code", sa.String(80)))
    op.add_column("crm_deliveries", sa.Column("verification_error_message", sa.String(1000)))
    op.create_index(
        "ix_crm_delivery_verification_dispatch",
        "crm_deliveries",
        ["verification_status", "next_verification_at"],
    )
    op.execute("UPDATE crm_deliveries SET retry_cycle_attempts = attempt_count")
    # Older versions could verify an empty response or unsupported connector.
    # Preserve their provider ACK but require new, positive verification evidence.
    op.execute(
        "UPDATE crm_deliveries SET status = 'acknowledged', verified_at = NULL WHERE acknowledged_at IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_index("ix_crm_delivery_verification_dispatch", table_name="crm_deliveries")
    for name in (
        "verification_error_message",
        "verification_error_code",
        "next_verification_at",
        "verification_status",
        "verification_evidence_json",
        "payload_json",
        "verification_cycle_attempts",
        "verification_attempt_count",
        "retry_cycle_attempts",
    ):
        op.drop_column("crm_deliveries", name)
