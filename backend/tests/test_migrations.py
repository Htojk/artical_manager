"""Alembic schema bootstrap and database constraint behavior."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import reset_settings_cache
from app.core.db import configure_engine, get_session_factory, reset_engine
from app.models import Base
from app.models.article import Article, DraftVersion

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _upgrade(settings) -> None:
    reset_settings_cache()
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", settings.effective_database_url.replace("%", "%%"))
    command.upgrade(config, "head")


def test_alembic_upgrade_creates_schema_and_is_idempotent(test_settings):
    _upgrade(test_settings)
    _upgrade(test_settings)

    engine = configure_engine(settings=test_settings)
    with engine.connect() as connection:
        tables = {
            row[0]
            for row in connection.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            )
        }
    assert set(Base.metadata.tables) <= tables
    assert "alembic_version" in tables

    with engine.connect() as connection:
        indexes = {
            row[1]
            for row in connection.execute(text("PRAGMA index_list('draft_versions')"))
        }
        ddl = connection.execute(
            text("SELECT sql FROM sqlite_master WHERE tbl_name='draft_versions'")
        ).fetchall()
    assert "ix_draft_versions_article_id" in indexes
    assert any("uq_draft_article_version" in (row[0] or "") for row in ddl)
    reset_engine()


def test_foreign_key_cascade_and_unique_constraint(test_settings):
    _upgrade(test_settings)
    engine = configure_engine(settings=test_settings)
    factory = get_session_factory()

    with factory() as session:
        article = Article(target_platforms=["mock"])
        session.add(article)
        session.commit()
        session.add(
            DraftVersion(article_id=article.id, version=1, content_md="正文")
        )
        session.commit()
        article_id = article.id

        session.add(DraftVersion(article_id=article_id, version=1, content_md="重复"))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

    with engine.begin() as connection:
        connection.execute(text("DELETE FROM articles WHERE id = :id"), {"id": article_id})
    with factory() as session:
        assert session.query(DraftVersion).filter_by(article_id=article_id).count() == 0
    reset_engine()
