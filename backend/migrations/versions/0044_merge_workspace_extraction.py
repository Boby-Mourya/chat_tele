"""Join onboarding and extraction without modifying either feature's data.

This merge is intentionally before subsequent workspace-access migrations so
both independently shipped 0044 histories are required by future upgrades.
"""

revision = "0044_merge_workspace_extraction"
down_revision = ("0044_workspace_onboarding", "0044_hybrid_extraction_review")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
