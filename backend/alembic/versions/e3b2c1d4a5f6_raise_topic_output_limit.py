"""Raise the default topic-selection output budget.

Revision ID: e3b2c1d4a5f6
Revises: c8e1d9a2b3f4
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e3b2c1d4a5f6"
down_revision: Union[str, Sequence[str], None] = "c8e1d9a2b3f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bindings = sa.table(
        "stage_model_bindings",
        sa.column("stage", sa.String()),
        sa.column("max_tokens", sa.Integer()),
    )
    op.execute(
        bindings.update()
        .where(bindings.c.stage == "topic_selection")
        .where(bindings.c.max_tokens == 4096)
        .values(max_tokens=8192)
    )


def downgrade() -> None:
    # Preserve the user's current model setting when rolling back schema revisions.
    pass
