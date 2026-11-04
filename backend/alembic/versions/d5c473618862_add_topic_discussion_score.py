"""add topic discussion score

Revision ID: d5c473618862
Revises: b1f2c3d4e5f6
Create Date: 2026-10-30 16:11:29.152415
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd5c473618862'
down_revision: Union[str, Sequence[str], None] = 'b1f2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("topics", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "discussion_score",
                sa.Float(),
                nullable=False,
                server_default="0",
            )
        )
        batch_op.add_column(
            sa.Column(
                "discussion_reason",
                sa.Text(),
                nullable=False,
                server_default="",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("topics", schema=None) as batch_op:
        batch_op.drop_column("discussion_reason")
        batch_op.drop_column("discussion_score")
