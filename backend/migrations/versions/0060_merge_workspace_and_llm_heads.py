"""Merge the workspace branding and LLM connection migration heads."""

from __future__ import annotations

from collections.abc import Sequence


revision: str = "0060_merge_workspace_and_llm_heads"
down_revision: tuple[str, str] = (
    "0059_merge_llm_connection_heads",
    "0059_workspace_brand_domain_resolver_normalized",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Merge the two schema branches without changing either schema."""


def downgrade() -> None:
    """Restore both branch heads when rolling back the merge revision."""
