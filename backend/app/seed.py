"""Idempotent bootstrap data: model profiles, stage bindings, settings, skills."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.content_strategy import ACCOUNT_PROFILE_KEY, AccountProfile
from app.core.constants import STAGE_ORDER, Stage
from app.models.llm import ModelProfile, StageModelBinding
from app.models.skill import Skill, SkillBinding
from app.models.system import Setting
from app.platforms.registry import PlatformRegistry
from app.skills.manager import SkillManager
from app.skills.registry import SkillRegistry

DEFAULT_SETTINGS = {
    ACCOUNT_PROFILE_KEY: AccountProfile().model_dump(),
    "publish_confirmation": True,
    "auto_review_advance": False,
    "max_revisions": 3,
    "review_pass_threshold": 75.0,
    "evolution_enabled": True,
    "metrics_interval_hours": 6.0,
    "evolution_interval_hours": 168.0,
}

DEFAULT_MODEL = {
    "name": "default-chat",
    "provider": "openai-compatible",
    "model": "gpt-4o-mini",
    "input_price_per_1k": 0.0011,
    "output_price_per_1k": 0.0043,
    "currency": "CNY",
    "context_window": 128000,
}

STAGE_MAX_TOKENS = {
    Stage.TOPIC: 8192,
    Stage.OUTLINE: 8192,
    Stage.WRITING: 16384,
    Stage.REVIEW: 12288,
}

STAGE_TEMPERATURES = {
    Stage.TOPIC: 0.9,
    Stage.RESEARCH: 0.2,
    Stage.OUTLINE: 0.5,
    Stage.WRITING: 0.7,
    Stage.TITLE: 0.85,
    Stage.REVIEW: 0.1,
    Stage.FORMATTING: 0.2,
    Stage.PUBLISHING: 0.2,
}


def seed_defaults(
    session: Session,
    *,
    settings: Settings | None = None,
    skill_registry: SkillRegistry | None = None,
    platform_registry: PlatformRegistry | None = None,
) -> dict:
    settings = settings or get_settings()
    created: dict[str, list[str]] = {
        "settings": [],
        "models": [],
        "bindings": [],
        "skills": [],
    }

    for key, value in _settings_payload(settings).items():
        existing = session.get(Setting, key)
        if existing is None:
            session.add(Setting(key=key, value=value))
            created["settings"].append(key)

    profile = session.scalar(select(ModelProfile).where(ModelProfile.name == DEFAULT_MODEL["name"]))
    if profile is None:
        # A custom model is unpriced unless prices are supplied, rather than
        # silently reusing the default gpt-4o-mini rates.
        input_price = settings.llm_input_price_per_1k
        output_price = settings.llm_output_price_per_1k
        if settings.llm_model == DEFAULT_MODEL["model"]:
            input_price = (
                DEFAULT_MODEL["input_price_per_1k"]
                if input_price is None
                else input_price
            )
            output_price = (
                DEFAULT_MODEL["output_price_per_1k"]
                if output_price is None
                else output_price
            )
        profile = ModelProfile(
            **{
                **DEFAULT_MODEL,
                "model": settings.llm_model,
                "input_price_per_1k": input_price,
                "output_price_per_1k": output_price,
            },
            base_url=settings.llm_base_url,
            api_key_env="APP_LLM_API_KEY",
        )
        session.add(profile)
        session.flush()
        created["models"].append(profile.name)

    for stage in STAGE_ORDER:
        binding = session.scalar(
            select(StageModelBinding).where(StageModelBinding.stage == stage)
        )
        if binding is None:
            session.add(
                StageModelBinding(
                    stage=stage,
                    model_profile_id=profile.id,
                    temperature=STAGE_TEMPERATURES.get(stage, 0.5),
                    max_tokens=STAGE_MAX_TOKENS.get(stage, 4096),
                )
            )
            created["bindings"].append(stage)
    session.commit()

    if skill_registry is not None:
        manager = SkillManager(session, skill_registry)
        skills = manager.sync()
        created["skills"] = [skill.slug for skill in skills]
        for skill in skills:
            if not skill.applies_to or Stage.WRITING not in skill.applies_to:
                continue
            binding = session.scalar(
                select(SkillBinding).where(
                    SkillBinding.stage == Stage.WRITING,
                    SkillBinding.skill_id == skill.id,
                )
            )
            if binding is None and skill.enabled:
                session.add(
                    SkillBinding(
                        stage=Stage.WRITING,
                        skill_id=skill.id,
                        order=len(
                            list(
                                session.scalars(
                                    select(SkillBinding).where(
                                        SkillBinding.stage == Stage.WRITING
                                    )
                                )
                            )
                        ),
                        enabled=True,
                    )
                )
        session.commit()

    if platform_registry is not None:
        platform_registry.discover()

    return created


def _settings_payload(settings: Settings) -> dict:
    payload = dict(DEFAULT_SETTINGS)
    payload.update(
        {
            "publish_confirmation": settings.publish_confirmation,
            "max_revisions": settings.max_revisions,
            "review_pass_threshold": settings.review_pass_threshold,
            "evolution_enabled": settings.evolution_enabled,
            "metrics_interval_hours": settings.metrics_interval_hours,
            "evolution_interval_hours": settings.evolution_interval_hours,
        }
    )
    return payload


def default_writing_skill_slug(session: Session) -> str | None:
    """Return the first enabled skill bound to the writing stage."""
    row = session.scalar(
        select(Skill.slug)
        .join(SkillBinding, SkillBinding.skill_id == Skill.id)
        .where(SkillBinding.stage == Stage.WRITING, SkillBinding.enabled.is_(True))
        .order_by(SkillBinding.order)
    )
    return row
