"""FastAPI dependencies backed by application state."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.db import get_db
from app.core.llm import LLMService
from app.platforms.registry import PlatformRegistry
from app.skills.registry import SkillRegistry


def session_dep() -> Generator[Session, None, None]:
    yield from get_db()


def get_llm(request: Request) -> LLMService:
    return request.app.state.llm


def get_runner(request: Request):
    return request.app.state.runner


def get_platforms(request: Request) -> PlatformRegistry:
    return request.app.state.platform_registry


def get_skills(request: Request) -> SkillRegistry:
    return request.app.state.skill_registry


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


SessionDep = Depends(session_dep)
LLMDep = Depends(get_llm)
RunnerDep = Depends(get_runner)
PlatformsDep = Depends(get_platforms)
SkillsDep = Depends(get_skills)
SettingsDep = Depends(get_app_settings)
