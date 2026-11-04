"""Model profile and stage binding endpoints."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import SessionDep
from app.api.schemas import ModelCreate, ModelUpdate, StageBindingUpdate
from app.api.serializers import model_binding_payload, model_payload
from app.core.constants import STAGE_ORDER
from app.core.errors import ConflictError, NotFoundError
from app.models.llm import ModelProfile, StageModelBinding

router = APIRouter(tags=["models"])


@router.get("/models")
def list_models(session: Session = SessionDep) -> dict:
    profiles = list(session.scalars(select(ModelProfile).order_by(ModelProfile.created_at)))
    return {"items": [model_payload(item) for item in profiles]}


@router.post("/models", status_code=201)
def create_model(payload: ModelCreate, session: Session = SessionDep) -> dict:
    existing = session.scalar(select(ModelProfile).where(ModelProfile.name == payload.name))
    if existing is not None:
        raise ConflictError("模型名称已存在")
    profile = ModelProfile(**payload.model_dump())
    session.add(profile)
    session.commit()
    session.refresh(profile)
    return model_payload(profile)


@router.patch("/models/{model_id}")
def update_model(
    model_id: str, payload: ModelUpdate, session: Session = SessionDep
) -> dict:
    profile = session.get(ModelProfile, model_id)
    if profile is None:
        raise NotFoundError("模型不存在")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(profile, key, value)
    session.commit()
    session.refresh(profile)
    return model_payload(profile)


@router.delete("/models/{model_id}", status_code=204)
def delete_model(model_id: str, session: Session = SessionDep) -> None:
    profile = session.get(ModelProfile, model_id)
    if profile is None:
        raise NotFoundError("模型不存在")
    bindings = session.scalar(
        select(StageModelBinding).where(StageModelBinding.model_profile_id == model_id).limit(1)
    )
    if bindings is not None:
        raise ConflictError("模型仍被阶段绑定使用，不能删除")
    session.delete(profile)
    session.commit()


@router.get("/model-bindings")
def list_bindings(session: Session = SessionDep) -> dict:
    rows = session.execute(
        select(StageModelBinding, ModelProfile)
        .join(ModelProfile, ModelProfile.id == StageModelBinding.model_profile_id)
        .order_by(StageModelBinding.stage)
    ).all()
    return {"items": [model_binding_payload(binding, profile) for binding, profile in rows]}


@router.put("/model-bindings/{stage}")
def upsert_binding(
    stage: str, payload: StageBindingUpdate, session: Session = SessionDep
) -> dict:
    if stage not in STAGE_ORDER:
        raise NotFoundError(f"未知阶段: {stage}")
    profile = session.get(ModelProfile, payload.model_profile_id)
    if profile is None:
        raise NotFoundError("模型不存在")
    binding = session.scalar(
        select(StageModelBinding).where(StageModelBinding.stage == stage)
    )
    if binding is None:
        binding = StageModelBinding(stage=stage, model_profile_id=profile.id)
        session.add(binding)
    binding.model_profile_id = payload.model_profile_id
    binding.temperature = payload.temperature
    binding.max_tokens = payload.max_tokens
    session.commit()
    session.refresh(binding)
    return model_binding_payload(binding, profile)
