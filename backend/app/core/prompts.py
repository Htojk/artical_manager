"""Jinja2 prompt template loading with strict variables."""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, TemplateNotFound

from app.core.config import get_settings
from app.core.errors import AppError


class PromptRenderError(AppError):
    code = "prompt_render_failed"
    status_code = 500


class PromptLoader:
    def __init__(self, prompts_dir: Path | str | None = None) -> None:
        self.prompts_dir = Path(prompts_dir or get_settings().prompts_dir)
        self.env = Environment(
            loader=FileSystemLoader(str(self.prompts_dir)),
            undefined=StrictUndefined,
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def render(self, name: str, **context: object) -> str:
        try:
            template = self.env.get_template(name)
        except TemplateNotFound as exc:
            raise PromptRenderError(f"提示词模板不存在: {name}") from exc
        try:
            return template.render(**context)
        except Exception as exc:  # noqa: BLE001 - surface clear message
            raise PromptRenderError(f"提示词渲染失败 {name}: {exc}") from exc
