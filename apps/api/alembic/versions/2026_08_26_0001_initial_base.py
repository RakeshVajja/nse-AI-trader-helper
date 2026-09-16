"""Initial base migration infrastructure.

Revision ID: 0001_initial_base
Revises:
Create Date: 2026-08-26 00:00:00.000000+00:00

"""

from __future__ import annotations

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "0001_initial_base"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Initial base schema state."""


def downgrade() -> None:
    """Revert initial base schema state."""
