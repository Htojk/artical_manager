"""Persist licensed image selections and formatting warnings.

Revision ID: c8e1d9a2b3f4
Revises: a7e4c1d2b3f0
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c8e1d9a2b3f4"
down_revision: Union[str, Sequence[str], None] = "a7e4c1d2b3f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "formatting_sources",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("article_id", sa.String(length=32), sa.ForeignKey("articles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("draft_id", sa.String(length=32), sa.ForeignKey("draft_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("content_md", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_formatting_sources_article_id", "formatting_sources", ["article_id"])
    op.create_index("ix_formatting_sources_draft_id", "formatting_sources", ["draft_id"], unique=True)
    with op.batch_alter_table("formatted_outputs") as batch_op:
        batch_op.add_column(sa.Column("warning", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("formatted_outputs") as batch_op:
        batch_op.drop_column("warning")
    op.drop_index("ix_formatting_sources_draft_id", table_name="formatting_sources")
    op.drop_index("ix_formatting_sources_article_id", table_name="formatting_sources")
    op.drop_table("formatting_sources")
