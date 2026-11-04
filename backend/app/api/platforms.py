"""Platform capability and credential endpoints (credentials are masked)."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter
from sqlalchemy.orm import Session

from app.api.deps import PlatformsDep, SessionDep
from app.api.schemas import CredentialUpdate
from app.core.errors import NotFoundError
from app.core.security import CredentialService
from app.platforms.base import PlatformAdapter

router = APIRouter(prefix="/platforms", tags=["platforms"])


@router.get("")
def list_platforms(session: Session = SessionDep, registry=PlatformsDep) -> dict:
    credentials = CredentialService(session)
    items = []
    for adapter in registry.all():
        payload = credentials.get(adapter.key)
        availability = adapter.validate(payload)
        items.append(_adapter_payload(adapter, availability, bool(payload)))
    return {"items": items}


@router.get("/{key}")
def get_platform(key: str, session: Session = SessionDep, registry=PlatformsDep) -> dict:
    adapter = registry.get(key)
    if adapter is None:
        raise NotFoundError(f"未知平台: {key}")
    credentials = CredentialService(session)
    payload = credentials.get(key)
    return _adapter_payload(adapter, adapter.validate(payload), bool(payload))


@router.get("/{key}/credentials")
def get_credentials(
    key: str, session: Session = SessionDep, registry=PlatformsDep
) -> dict:
    if registry.get(key) is None:
        raise NotFoundError(f"未知平台: {key}")
    return {"platform": key, "masked": CredentialService(session).masked(key)}


@router.put("/{key}/credentials")
def set_credentials(
    key: str,
    payload: CredentialUpdate,
    session: Session = SessionDep,
    registry=PlatformsDep,
) -> dict:
    if registry.get(key) is None:
        raise NotFoundError(f"未知平台: {key}")
    service = CredentialService(session)
    service.set(key, payload.payload)
    return {"platform": key, "masked": service.masked(key)}


@router.delete("/{key}/credentials", status_code=204)
def delete_credentials(
    key: str, session: Session = SessionDep, registry=PlatformsDep
) -> None:
    if registry.get(key) is None:
        raise NotFoundError(f"未知平台: {key}")
    CredentialService(session).delete(key)


def _adapter_payload(adapter: PlatformAdapter, availability, has_credentials: bool) -> dict:
    return {
        "key": adapter.key,
        "display_name": adapter.display_name,
        "capabilities": asdict(adapter.capabilities),
        "available": availability.available,
        "mode": availability.mode,
        "reason": availability.reason,
        "has_credentials": has_credentials,
    }
