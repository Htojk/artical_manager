"""add title optimization stage

Revision ID: b1f2c3d4e5f6
Revises: 8dd6e493d708
Create Date: 2026-10-30 16:40:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b1f2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "8dd6e493d708"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("articles", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("current_title_version", sa.Integer(), nullable=True)
        )

    op.create_table(
        "title_versions",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("article_id", sa.String(length=32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("candidates", sa.JSON(), nullable=False),
        sa.Column("selected_title", sa.String(length=500), nullable=False),
        sa.Column("strategy", sa.Text(), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(length=16), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["article_id"], ["articles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("article_id", "version", name="uq_title_article_version"),
    )
    op.create_index(
        "ix_title_versions_article_id", "title_versions", ["article_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_title_versions_article_id", table_name="title_versions")
    op.drop_table("title_versions")
    with op.batch_alter_table("articles", schema=None) as batch_op:
        batch_op.drop_column("current_title_version")
