"""Join workspace, course-knowledge, and enrollment-aware Education histories."""

from __future__ import annotations


revision = "0050_merge_course_education_heads"
down_revision = (
    "0045_starter_template_clones",
    "0046_course_study_receipts",
    "0049_education_enrollment_paper_access",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    """The parent revisions own their schema changes; this revision joins them."""


def downgrade() -> None:
    """Downgrading separates the histories without changing their schemas."""
