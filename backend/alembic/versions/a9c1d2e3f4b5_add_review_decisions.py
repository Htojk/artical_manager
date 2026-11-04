"""add review decisions

Store human approve/reject decisions taken at the review gate.

Revision ID: a9c1d2e3f4b5
Revises: f6a7b8c9d0e1
Create Date: 2026-11-03 10:00:00
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a9c1d2e3f4b5"
down_revision: Union[str, Sequence[str], None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "review_decisions",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("article_id", sa.String(length=32), nullable=False),
        sa.Column("run_id", sa.String(length=32), nullable=False),
        sa.Column("report_id", sa.String(length=32), nullable=True),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("feedback", sa.Text(), nullable=False),
        sa.Column("rollback_to", sa.String(length=32), nullable=True),
        sa.Column("target_reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["article_id"], ["articles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["workflow_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["report_id"], ["review_reports.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_review_decisions_article_id", "review_decisions", ["article_id"])
    op.create_index("ix_review_decisions_run_id", "review_decisions", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_review_decisions_run_id", table_name="review_decisions")
    op.drop_index("ix_review_decisions_article_id", table_name="review_decisions")
    op.drop_table("review_decisions")
