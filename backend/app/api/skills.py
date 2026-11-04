"""Skill management endpoints."""

from __future__ import annotations

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import SessionDep, SkillsDep
from app.api.schemas import SkillBindRequest, SkillCreate, SkillEdit, SkillToggle
from app.api.serializers import (
    binding_payload,
    skill_detail_payload,
    skill_payload,
)
from app.core.errors import NotFoundError, PayloadTooLargeError
from app.models.skill import Skill, SkillBinding, SkillVersion
from app.skills.importer import MAX_UPLOAD_BYTES
from app.skills.manager import SkillManager

router = APIRouter(tags=["skills"])


def _skill_detail(slug: str, session: Session, registry) -> dict:
    skill = session.scalar(select(Skill).where(Skill.slug == slug))
    if skill is None:
        raise NotFoundError(f"技能不存在: {slug}")
    versions = list(
        session.scalars(
            select(SkillVersion)
            .where(SkillVersion.skill_id == skill.id)
            .order_by(SkillVersion.created_at.desc())
        )
    )
    info = registry.get(slug)
    payload = skill_detail_payload(skill, info)
    payload["content"] = info.raw if info is not None else None
    payload["versions"] = [
        {
            "id": version.id,
            "version": version.version,
            "note": version.note,
            "created_at": version.created_at.isoformat(),
        }
        for version in versions
    ]
    return payload


@router.get("/skills")
def list_skills(session: Session = SessionDep, registry=SkillsDep) -> dict:
    manager = SkillManager(session, registry)
    manager.sync()
    skills = manager.list_skills()
    return {"items": [skill_payload(item) for item in skills]}


@router.post("/skills", status_code=201)
def create_skill(
    payload: SkillCreate, session: Session = SessionDep, registry=SkillsDep
) -> dict:
    manager = SkillManager(session, registry)
    skill = manager.create_skill(
        payload.slug,
        description=payload.description,
        display_name=payload.display_name,
        content=payload.content,
        version=payload.version,
        applies_to=payload.applies_to,
    )
    return skill_payload(skill)


@router.post("/skills/import", status_code=201)
def import_skill(
    file: UploadFile = File(...),
    slug: str = Form(""),
    session: Session = SessionDep,
    registry=SkillsDep,
) -> dict:
    filename = file.filename or ""
    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise PayloadTooLargeError("ZIP 文件不能超过 20 MB")
    result = SkillManager(session, registry).import_skill(
        data, filename=filename, slug=slug
    )
    payload = _skill_detail(result.skill.slug, session, registry)
    payload["imported_files"] = result.imported_files
    payload["source_filename"] = filename
    return payload


@router.delete("/skills/{slug}", status_code=204)
def delete_skill(slug: str, session: Session = SessionDep, registry=SkillsDep) -> None:
    SkillManager(session, registry).delete_skill(slug)


@router.get("/skills/{slug}")
def get_skill(slug: str, session: Session = SessionDep, registry=SkillsDep) -> dict:
    return _skill_detail(slug, session, registry)


@router.get("/skills/{slug}/export")
def export_skill(slug: str, session: Session = SessionDep, registry=SkillsDep) -> Response:
    data = SkillManager(session, registry).export_skill(slug)
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{slug}.zip"'},
    )


@router.put("/skills/{slug}/content")
def edit_skill(
    slug: str, payload: SkillEdit, session: Session = SessionDep, registry=SkillsDep
) -> dict:
    manager = SkillManager(session, registry)
    skill = manager.edit_content(slug, payload.content, note=payload.note)
    return skill_payload(skill)


@router.post("/skills/{slug}/toggle")
def toggle_skill(
    slug: str, payload: SkillToggle, session: Session = SessionDep, registry=SkillsDep
) -> dict:
    manager = SkillManager(session, registry)
    skill = manager.set_enabled(slug, payload.enabled)
    return skill_payload(skill)


@router.post("/skills/{slug}/rollback/{version_id}")
def rollback_skill(
    slug: str, version_id: str, session: Session = SessionDep, registry=SkillsDep
) -> dict:
    manager = SkillManager(session, registry)
    skill = manager.rollback(slug, version_id)
    return skill_payload(skill)


@router.get("/skill-bindings")
def list_bindings(session: Session = SessionDep, stage: str | None = None) -> dict:
    query = select(SkillBinding, Skill).join(Skill, Skill.id == SkillBinding.skill_id)
    if stage:
        query = query.where(SkillBinding.stage == stage)
    rows = session.execute(query.order_by(SkillBinding.stage, SkillBinding.order)).all()
    return {"items": [binding_payload(binding, skill) for binding, skill in rows]}


@router.post("/skill-bindings", status_code=201)
def create_binding(
    payload: SkillBindRequest, session: Session = SessionDep, registry=SkillsDep
) -> dict:
    binding = SkillManager(session, registry).bind(
        payload.stage, payload.slug, order=payload.order, enabled=payload.enabled
    )
    skill = session.get(Skill, binding.skill_id)
    return binding_payload(binding, skill)


@router.delete("/skill-bindings/{binding_id}", status_code=204)
def delete_binding(
    binding_id: str, session: Session = SessionDep, registry=SkillsDep
) -> None:
    SkillManager(session, registry).unbind(binding_id)
