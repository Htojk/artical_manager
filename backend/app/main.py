"""FastAPI application factory."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import analytics, articles, events, evolution, health, models, platforms
from app.api import publishing, runs, settings as settings_api, skills, sources, stages, topics
from app.article_generation.workflow.runner import WorkflowRunner
from app.core.config import Settings, get_settings
from app.core.db import (
    configure_engine,
    get_session_factory,
    init_db,
    reset_engine,
)
from app.core.errors import AppError
from app.core.events import event_bus
from app.core.llm import LLMService
from app.core.logging import configure_logging
from app.core.tracing import configure_tracing, shutdown_tracing
from app.platforms.registry import registry as global_registry
from app.platforms.registry import PlatformRegistry
from app.seed import seed_defaults
from app.skills.registry import SkillRegistry
from app.tasks import collect_metrics_job, evolution_analysis_job

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    *,
    llm: LLMService | None = None,
    runner: WorkflowRunner | None = None,
    platform_registry: PlatformRegistry | None = None,
    skill_registry: SkillRegistry | None = None,
    start_scheduler: bool = True,
) -> FastAPI:
    app_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        configure_logging("INFO", log_dir=app_settings.log_dir)
        configure_tracing(app_settings)
        app_settings.ensure_directories()
        configure_engine(app_settings.effective_database_url, settings=app_settings)
        init_db()
        session_factory = get_session_factory()

        platforms_registry = platform_registry or global_registry
        platforms_registry.discover()
        skills_registry = skill_registry or SkillRegistry(app_settings.skills_dir)
        llm_service = llm or LLMService(session_factory, settings=app_settings)
        runner_service = runner or WorkflowRunner(
            session_factory,
            llm_service,
            platforms_registry,
            skills_registry,
            settings=app_settings,
        )

        with session_factory() as session:
            seed_defaults(
                session,
                settings=app_settings,
                skill_registry=skills_registry,
                platform_registry=platforms_registry,
            )

        app.state.settings = app_settings
        app.state.llm = llm_service
        app.state.runner = runner_service
        app.state.platform_registry = platforms_registry
        app.state.skill_registry = skills_registry
        app.state.session_factory = session_factory

        try:
            event_bus.bind_loop(asyncio.get_running_loop())
        except RuntimeError:
            pass
        runner_service.recover_orphans()

        scheduler: AsyncIOScheduler | None = None
        if start_scheduler:
            scheduler = AsyncIOScheduler(timezone="UTC")
            scheduler.add_job(
                collect_metrics_job,
                IntervalTrigger(hours=app_settings.metrics_interval_hours),
                args=[session_factory, platforms_registry],
                id="metrics",
                replace_existing=True,
                max_instances=1,
                coalesce=True,
            )
            if app_settings.evolution_enabled:
                scheduler.add_job(
                    evolution_analysis_job,
                    IntervalTrigger(hours=app_settings.evolution_interval_hours),
                    args=[session_factory, llm_service],
                    id="evolution",
                    replace_existing=True,
                    max_instances=1,
                    coalesce=True,
                )
            scheduler.start()
        app.state.scheduler = scheduler
        try:
            yield
        finally:
            if scheduler is not None:
                scheduler.shutdown(wait=False)
            shutdown_tracing()
            reset_engine()

    app = FastAPI(
        title=app_settings.app_name,
        version="0.1.0",
        description="自动写稿与发布 agent：选题、调研、写作、审核、排版、发布与自进化。",
        lifespan=lifespan,
        openapi_tags=[
            {"name": "system", "description": "健康检查与系统信息"},
            {"name": "articles", "description": "文章管理"},
            {"name": "topics", "description": "选题推荐与选择"},
            {"name": "runs", "description": "工作流运行控制"},
            {"name": "stages", "description": "阶段产物与时间线"},
            {"name": "publishing", "description": "排版、发布与手动回填"},
            {"name": "analytics", "description": "运维分析"},
            {"name": "skills", "description": "技能管理"},
            {"name": "models", "description": "模型与阶段绑定"},
            {"name": "settings", "description": "运行配置"},
            {"name": "platforms", "description": "平台能力与凭据"},
            {"name": "evolution", "description": "自进化建议"},
            {"name": "events", "description": "SSE 实时事件"},
        ],
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(AppError)
    async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "code": exc.code,
                "message": exc.message,
                "details": jsonable_encoder(exc.details),
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "code": "validation_error",
                "message": "请求参数校验失败",
                "details": jsonable_encoder(exc.errors()),
            },
        )

    @app.exception_handler(HTTPException)
    async def http_error_handler(_request: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "code": "http_error",
                "message": str(exc.detail),
                "details": None,
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(_request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error: %s", exc)
        return JSONResponse(
            status_code=500,
            content={
                "code": "internal_error",
                "message": "服务器内部错误",
                "details": None,
            },
        )

    api_prefix = "/api"
    for module in (
        health,
        articles,
        topics,
        runs,
        sources,
        stages,
        publishing,
        analytics,
        skills,
        models,
        settings_api,
        platforms,
        evolution,
        events,
    ):
        app.include_router(module.router, prefix=api_prefix)

    @app.get("/", include_in_schema=False)
    def root() -> dict[str, Any]:
        return {"name": app_settings.app_name, "docs": "/docs", "health": "/api/health"}

    return app


app = create_app()
