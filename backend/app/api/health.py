"""Health probe."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.api.deps import SessionDep, SettingsDep
from app.core.config import Settings
from app.core.security import CredentialService
from app.models.system import Setting
from app.monitoring.connectivity import ConnectivityChecker, REPORT_SETTING_KEY
from app.models.article import Article

router = APIRouter(tags=["system"])


@router.get("/health")
def health(session: Session = SessionDep) -> dict:
    session.execute(text("SELECT 1"))
    articles = session.scalar(select(func.count(Article.id))) or 0
    return {
        "status": "ok",
        "database": "ok",
        "articles": int(articles),
    }


@router.get("/health/connectivity")
def connectivity_report(session: Session = SessionDep) -> dict:
    row = session.get(Setting, REPORT_SETTING_KEY)
    return row.value if row else {
        "checked_at": None,
        "status": "not_checked",
        "summary": {"ok": 0, "failed": 0, "skipped": 0},
        "items": [],
    }


@router.post("/health/connectivity/check")
def check_connectivity(
    session: Session = SessionDep, settings: Settings = SettingsDep
) -> dict:
    credentials = CredentialService(session).get("wechat")
    report = ConnectivityChecker(settings, credentials).run()
    row = session.get(Setting, REPORT_SETTING_KEY)
    if row is None:
        session.add(Setting(key=REPORT_SETTING_KEY, value=report))
    else:
        row.value = report
    session.commit()
    return report
