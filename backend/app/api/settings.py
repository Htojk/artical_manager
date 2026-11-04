"""Runtime setting endpoints."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import SessionDep
from app.api.schemas import SettingUpdate
from app.content_strategy import ACCOUNT_PROFILE_KEY, AccountProfile
from app.core.errors import NotFoundError, ValidationError
from app.models.system import Setting

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("")
def list_settings(session: Session = SessionDep) -> dict:
    rows = list(session.scalars(select(Setting).order_by(Setting.key)))
    return {
        "items": [
            {
                "key": row.key,
                "value": row.value,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            }
            for row in rows
        ]
    }


@router.get("/{key}")
def get_setting(key: str, session: Session = SessionDep) -> dict:
    row = session.get(Setting, key)
    if row is None:
        raise NotFoundError(f"配置项不存在: {key}")
    return {"key": row.key, "value": row.value}


@router.put("/{key}")
def update_setting(key: str, payload: SettingUpdate, session: Session = SessionDep) -> dict:
    value = payload.value
    if key == ACCOUNT_PROFILE_KEY:
        try:
            value = AccountProfile.model_validate(value).model_dump()
        except PydanticValidationError as exc:
            raise ValidationError(f"账号画像无效: {exc}") from exc
    row = session.get(Setting, key)
    if row is None:
        row = Setting(key=key, value=value)
        session.add(row)
    else:
        row.value = value
    session.commit()
    session.refresh(row)
    return {"key": row.key, "value": row.value}
