"""add entertainment topic scores and content format

Revision ID: a7e4c1d2b3f0
Revises: a9c1d2e3f4b5
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a7e4c1d2b3f0"
down_revision: Union[str, Sequence[str], None] = "a9c1d2e3f4b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("topics") as batch_op:
        batch_op.add_column(sa.Column("entertainment_score", sa.Float(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("entertainment_reason", sa.Text(), nullable=False, server_default=""))
        batch_op.add_column(sa.Column("entertainment_scores", sa.JSON(), nullable=False, server_default="{}"))
        batch_op.add_column(sa.Column("content_format", sa.String(40), nullable=False, server_default="hot_take"))


def downgrade() -> None:
    with op.batch_alter_table("topics") as batch_op:
        batch_op.drop_column("content_format")
        batch_op.drop_column("entertainment_scores")
        batch_op.drop_column("entertainment_reason")
        batch_op.drop_column("entertainment_score")
