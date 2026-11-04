"""raise generation token limits

Long articles and review reports regularly exceed the old 4096 completion
limit, which truncated JSON and forced unreliable repair turns.

Revision ID: f6a7b8c9d0e1
Revises: d5c473618862
Create Date: 2026-11-02 21:50:00
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, Sequence[str], None] = "d5c473618862"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


LIMITS = {"outline": 8192, "writing": 16384, "review": 12288}


def upgrade() -> None:
    bindings = sa.table(
        "stage_model_bindings",
        sa.column("stage", sa.String()),
        sa.column("max_tokens", sa.Integer()),
    )
    for stage, limit in LIMITS.items():
        op.execute(
            bindings.update()
            .where(bindings.c.stage == stage)
            .where(bindings.c.max_tokens <= limit)
            .values(max_tokens=limit)
        )


def downgrade() -> None:
    bindings = sa.table(
        "stage_model_bindings",
        sa.column("stage", sa.String()),
        sa.column("max_tokens", sa.Integer()),
    )
    for stage in LIMITS:
        op.execute(bindings.update().where(bindings.c.stage == stage).values(max_tokens=4096))
