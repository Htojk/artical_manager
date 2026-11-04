"""Filesystem skill discovery and Agent Skills front-matter validation."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

REQUIRED_FIELDS = ("name", "description")
MAX_NAME_LENGTH = 64
MAX_DESCRIPTION_LENGTH = 1024
RESOURCE_DIRS = ("references", "scripts", "assets")


@dataclass
class SkillInfo:
    slug: str
    name: str = ""
    standard_name: str = ""
    description: str = ""
    version: str = "1.0.0"
    applies_to: list[str] = field(default_factory=list)
    entry: str = "SKILL.md"
    path: Path | None = None
    content: str = ""
    raw: str = ""
    license: str = ""
    compatibility: str = ""
    allowed_tools: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    resources: list[dict] = field(default_factory=list)
    status: str = "valid"
    error: str | None = None
    mtime: float = 0.0

    @property
    def valid(self) -> bool:
        return self.status == "valid"


def parse_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        raise ValueError("缺少 YAML frontmatter")
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise ValueError("frontmatter 未闭合")
    meta = yaml.safe_load(parts[1]) or {}
    if not isinstance(meta, dict):
        raise ValueError("frontmatter 必须是对象")
    return meta, parts[2].strip()


def _string_list(value: object) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _text(value: object) -> str:
    return str(value).strip() if value is not None else ""


def _metadata(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _scan_resources(skill_dir: Path) -> list[dict]:
    """List bundled resources without following paths outside the skill directory."""
    root = skill_dir.resolve()
    resources: list[dict] = []
    for name in RESOURCE_DIRS:
        directory = skill_dir / name
        if not directory.is_dir():
            continue
        for item in directory.rglob("*"):
            if not item.is_file():
                continue
            try:
                relative = item.resolve().relative_to(root)
            except (OSError, ValueError):
                continue
            if any(part.startswith(".") for part in relative.parts):
                continue
            try:
                size = item.stat().st_size
            except OSError:
                continue
            resources.append({"path": relative.as_posix(), "size": size})
    return sorted(resources, key=lambda item: item["path"])


class SkillLoader:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    def scan(self) -> list[SkillInfo]:
        if not self.root.exists():
            return []
        skills: list[SkillInfo] = []
        for skill_dir in sorted(self.root.iterdir()):
            if not skill_dir.is_dir() or skill_dir.name.startswith("."):
                continue
            skills.append(self.load_directory(skill_dir))
        return skills

    def load_directory(self, skill_dir: Path) -> SkillInfo:
        info = SkillInfo(slug=skill_dir.name, path=skill_dir)
        try:
            manifest = skill_dir / "SKILL.md"
            if not manifest.exists():
                raise ValueError("缺少 SKILL.md")
            text = manifest.read_text(encoding="utf-8")
            meta, body = parse_frontmatter(text)
            entry_name = _text(meta.get("entry")) or "SKILL.md"
            entry_file = skill_dir / entry_name
            if not entry_file.exists():
                raise ValueError(f"入口文件不存在: {entry_name}")
            if entry_name != "SKILL.md":
                body = entry_file.read_text(encoding="utf-8")

            metadata = _metadata(meta.get("metadata"))
            standard_name = _text(meta.get("name"))
            display_name = _text(metadata.get("display_name")) or standard_name
            info = SkillInfo(
                slug=skill_dir.name,
                name=display_name,
                standard_name=standard_name,
                description=_text(meta.get("description")),
                version=_text(meta.get("version")) or "1.0.0",
                applies_to=_string_list(meta.get("applies_to")),
                entry=entry_name,
                path=skill_dir,
                content=body,
                raw=text,
                license=_text(meta.get("license")),
                compatibility=_text(meta.get("compatibility")),
                allowed_tools=_string_list(
                    meta.get("allowed-tools") or meta.get("allowed_tools")
                ),
                metadata=metadata,
                resources=_scan_resources(skill_dir),
                mtime=max(manifest.stat().st_mtime, entry_file.stat().st_mtime),
            )
            missing = [
                field_name
                for field_name in REQUIRED_FIELDS
                if not getattr(info, field_name)
            ]
            if missing:
                raise ValueError(f"缺少必填字段: {', '.join(missing)}")
            if len(info.standard_name) > MAX_NAME_LENGTH:
                raise ValueError(f"name 不能超过 {MAX_NAME_LENGTH} 个字符")
            if len(info.description) > MAX_DESCRIPTION_LENGTH:
                raise ValueError(f"description 不能超过 {MAX_DESCRIPTION_LENGTH} 个字符")
            if not isinstance(meta.get("applies_to", []), list):
                raise ValueError("applies_to 必须是列表")
        except Exception as exc:  # noqa: BLE001 - invalid skill must not break startup
            info.status = "invalid"
            info.error = str(exc)
            try:
                info.mtime = max(
                    (
                        item.stat().st_mtime
                        for item in skill_dir.rglob("*")
                        if item.is_file()
                    ),
                    default=0.0,
                )
            except OSError:
                info.mtime = 0.0
            logger.warning("skill %s is invalid: %s", skill_dir.name, exc)
        return info
