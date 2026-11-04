"""Persist skills in SQLite, bind them to stages and inject their content."""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.constants import SKILL_STAGE_KEYS
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.models.skill import Skill, SkillBinding, SkillVersion
from app.skills.exporter import build_skill_zip
from app.skills.importer import extract_skill_zip
from app.skills.loader import (
    MAX_DESCRIPTION_LENGTH,
    MAX_NAME_LENGTH,
    SkillInfo,
    parse_frontmatter,
)
from app.skills.registry import SkillRegistry

SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


@dataclass
class ImportedSkill:
    skill: Skill
    imported_files: int


def normalize_slug(value: str) -> str:
    """Turn an arbitrary directory or archive name into a valid slug."""
    slug = re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower()).strip("-")
    return slug[:MAX_NAME_LENGTH].strip("-")


@dataclass
class SkillInjection:
    text: str = ""
    skills: list[dict] = field(default_factory=list)
    degraded: list[dict] = field(default_factory=list)


class SkillManager:
    def __init__(
        self,
        session: Session,
        registry: SkillRegistry,
        *,
        trash_dir: Path | None = None,
    ) -> None:
        self.session = session
        self.registry = registry
        self.trash_dir = Path(trash_dir or (get_settings().data_dir / "skill-trash"))

    def sync(self) -> list[Skill]:
        skills: list[Skill] = []
        for info in self.registry.reload():
            skill = self.session.scalar(select(Skill).where(Skill.slug == info.slug))
            if skill is None:
                skill = Skill(slug=info.slug)
                self.session.add(skill)
            skill.name = info.name or info.slug
            skill.version = info.version or skill.version
            skill.description = info.description
            skill.applies_to = info.applies_to
            skill.source_path = str(info.path or "")
            skill.status = info.status
            skill.error = info.error
            skills.append(skill)
        self.session.commit()
        return skills

    def list_skills(self) -> list[Skill]:
        return list(self.session.scalars(select(Skill).order_by(Skill.name)))

    def set_enabled(self, slug: str, enabled: bool) -> Skill:
        skill = self.session.scalar(select(Skill).where(Skill.slug == slug))
        if skill is None:
            raise NotFoundError(f"技能不存在: {slug}")
        skill.enabled = enabled
        self.session.commit()
        return skill

    def bind(self, stage: str, slug: str, order: int = 0, enabled: bool = True) -> SkillBinding:
        skill = self.session.scalar(select(Skill).where(Skill.slug == slug))
        if skill is None:
            raise NotFoundError(f"技能不存在: {slug}")
        if stage not in SKILL_STAGE_KEYS:
            raise ValidationError(f"阶段 {stage} 不支持技能注入")
        binding = self.session.scalar(
            select(SkillBinding).where(
                SkillBinding.stage == stage, SkillBinding.skill_id == skill.id
            )
        )
        if binding is None:
            binding = SkillBinding(stage=stage, skill_id=skill.id, order=order, enabled=enabled)
            self.session.add(binding)
        else:
            binding.order = order
            binding.enabled = enabled
        self.session.commit()
        return binding

    def unbind(self, binding_id: str) -> None:
        binding = self.session.get(SkillBinding, binding_id)
        if binding is None:
            raise NotFoundError("技能绑定不存在")
        self.session.delete(binding)
        self.session.commit()

    def render_for_stage(self, stage: str) -> SkillInjection:
        rows = self.session.execute(
            select(SkillBinding, Skill)
            .join(Skill, Skill.id == SkillBinding.skill_id)
            .where(SkillBinding.stage == stage)
            .order_by(SkillBinding.order, SkillBinding.id)
        ).all()
        texts: list[str] = []
        used: list[dict] = []
        degraded: list[dict] = []
        for binding, skill in rows:
            if not binding.enabled:
                continue
            if not skill.enabled:
                degraded.append({"slug": skill.slug, "reason": "技能已停用"})
                continue
            info = self.registry.get(skill.slug)
            if info is None or not info.valid:
                degraded.append(
                    {"slug": skill.slug, "reason": info.error if info else "技能文件缺失"}
                )
                continue
            texts.append(f"## 技能：{info.name}\n\n{info.content}")
            used.append({"slug": info.slug, "name": info.name, "version": info.version})
        return SkillInjection(text="\n\n".join(texts), skills=used, degraded=degraded)

    def system_prompt(self, stage: str, base: str) -> str:
        injection = self.render_for_stage(stage)
        if not injection.text:
            return base
        return f"{base.rstrip()}\n\n## 本阶段技能要求\n\n{injection.text}"

    def _skill_dir(self, slug: str) -> Path:
        root = self.registry.loader.root.resolve()
        path = (root / slug).resolve()
        if path == root or root not in path.parents:
            raise ValidationError(f"技能路径越界: {slug}")
        return path

    @staticmethod
    def _parse_standard(content: str) -> tuple[dict, str, str, str]:
        try:
            meta, _ = parse_frontmatter(content)
        except ValueError as exc:
            raise ValidationError(f"技能内容无效: {exc}") from exc
        name = str(meta.get("name") or "").strip()
        description = str(meta.get("description") or "").strip()
        missing = [field for field, value in (("name", name), ("description", description)) if not value]
        if missing:
            raise ValidationError(f"缺少必填字段: {', '.join(missing)}")
        if len(name) > MAX_NAME_LENGTH:
            raise ValidationError(f"name 不能超过 {MAX_NAME_LENGTH} 个字符")
        if len(description) > MAX_DESCRIPTION_LENGTH:
            raise ValidationError(f"description 不能超过 {MAX_DESCRIPTION_LENGTH} 个字符")
        metadata = meta.get("metadata") if isinstance(meta.get("metadata"), dict) else {}
        display_name = str(metadata.get("display_name") or name).strip()
        version = str(meta.get("version") or "1.0.0").strip()
        applies_to = meta.get("applies_to", [])
        if not isinstance(applies_to, list):
            raise ValidationError("applies_to 必须是列表")
        return meta, display_name, version, list(applies_to)

    def create_skill(
        self,
        slug: str,
        *,
        description: str,
        display_name: str = "",
        content: str = "",
        version: str = "1.0.0",
        applies_to: list[str] | None = None,
    ) -> Skill:
        slug = slug.strip()
        description = description.strip()
        if not slug or len(slug) > MAX_NAME_LENGTH or not SLUG_PATTERN.fullmatch(slug):
            raise ValidationError("slug 只能包含小写字母、数字与连字符，且不超过 64 个字符")
        if not description:
            raise ValidationError("description 不能为空")
        if len(description) > MAX_DESCRIPTION_LENGTH:
            raise ValidationError(f"description 不能超过 {MAX_DESCRIPTION_LENGTH} 个字符")
        if self.session.scalar(select(Skill).where(Skill.slug == slug)) is not None:
            raise ConflictError(f"技能已存在: {slug}")
        directory = self._skill_dir(slug)
        if directory.exists():
            raise ConflictError(f"技能目录已存在: {slug}")
        stages = [str(stage) for stage in (applies_to or []) if str(stage).strip()]
        if any(stage not in SKILL_STAGE_KEYS for stage in stages):
            raise ValidationError("applies_to 包含不支持的阶段")

        meta: dict = {
            "name": slug,
            "description": description,
            "version": version.strip() or "1.0.0",
        }
        display_name = display_name.strip()
        if display_name and display_name != slug:
            meta["metadata"] = {"display_name": display_name}
        if stages:
            meta["applies_to"] = stages
        frontmatter = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False).strip()
        text = f"---\n{frontmatter}\n---\n\n{content.strip()}\n"

        directory.parent.mkdir(parents=True, exist_ok=True)
        directory.mkdir()
        try:
            (directory / "SKILL.md").write_text(text, encoding="utf-8")
            info = self.registry.loader.load_directory(directory)
            if not info.valid:
                raise ValidationError(f"技能内容无效: {info.error}")
            self.sync()
            skill = self.session.scalar(select(Skill).where(Skill.slug == slug))
            if skill is None:
                raise ValidationError("技能同步失败")
            skill.versions.append(
                SkillVersion(version=info.version, content=text, note="创建技能")
            )
            self.session.commit()
            self.registry.reload()
            return skill
        except Exception:
            self.session.rollback()
            leftover = self.session.scalar(select(Skill).where(Skill.slug == slug))
            if leftover is not None:
                self.session.delete(leftover)
                self.session.commit()
            shutil.rmtree(directory, ignore_errors=True)
            self.registry.reload()
            raise

    def _ensure_slug_available(self, slug: str) -> Path:
        directory = self._skill_dir(slug)
        if self.session.scalar(select(Skill).where(Skill.slug == slug)) is not None:
            raise ConflictError(f"技能已存在: {slug}")
        if directory.exists():
            raise ConflictError(f"技能目录已存在: {slug}")
        return directory

    def import_skill(
        self,
        data: bytes,
        *,
        filename: str = "",
        slug: str = "",
    ) -> ImportedSkill:
        """Import a ZIP skill package into ``skills/<slug>/`` atomically."""
        filename = Path(filename or "").name
        explicit = slug.strip()
        if explicit:
            if len(explicit) > MAX_NAME_LENGTH or not SLUG_PATTERN.fullmatch(explicit):
                raise ValidationError(
                    "slug 只能包含小写字母、数字与连字符，且不超过 64 个字符"
                )
            self._ensure_slug_available(explicit)

        root = self.registry.loader.root.resolve()
        root.mkdir(parents=True, exist_ok=True)
        staging = root / f".import-{uuid4().hex}"
        target_slug = explicit
        directory: Path | None = None
        moved = False
        try:
            imported_files, hint = extract_skill_zip(data, staging)
            if not target_slug:
                candidate = normalize_slug(hint) or normalize_slug(Path(filename).stem)
                if not candidate:
                    raise ValidationError("无法从压缩包推断 slug，请提供 slug")
                target_slug = candidate
            directory = self._ensure_slug_available(target_slug)

            info = self.registry.loader.load_directory(staging)
            if not info.valid:
                raise ValidationError(f"技能内容无效: {info.error}")

            staging.rename(directory)
            moved = True
            self.sync()
            skill = self.session.scalar(select(Skill).where(Skill.slug == target_slug))
            if skill is None:
                raise ValidationError("技能同步失败")
            note = f"导入 zip：{filename}" if filename else "导入 zip"
            skill.versions.append(
                SkillVersion(version=info.version, content=info.raw, note=note)
            )
            self.session.commit()
            self.registry.reload()
            return ImportedSkill(skill=skill, imported_files=imported_files)
        except Exception:
            self.session.rollback()
            # Only undo the install when this call moved the package into place;
            # never delete a pre-existing skill that caused a conflict.
            if moved:
                if target_slug:
                    leftover = self.session.scalar(
                        select(Skill).where(Skill.slug == target_slug)
                    )
                    if leftover is not None:
                        self.session.delete(leftover)
                        self.session.commit()
                if directory is not None:
                    shutil.rmtree(directory, ignore_errors=True)
            shutil.rmtree(staging, ignore_errors=True)
            self.registry.reload()
            raise

    def export_skill(self, slug: str) -> bytes:
        skill = self.session.scalar(select(Skill).where(Skill.slug == slug))
        if skill is None:
            raise NotFoundError(f"技能不存在: {slug}")
        return build_skill_zip(self._skill_dir(slug), slug)

    def delete_skill(self, slug: str) -> Path | None:
        skill = self.session.scalar(select(Skill).where(Skill.slug == slug))
        if skill is None:
            raise NotFoundError(f"技能不存在: {slug}")
        directory = self._skill_dir(slug)
        trashed: Path | None = None
        if directory.exists():
            self.trash_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
            trashed = self.trash_dir / f"{slug}-{stamp}-{uuid4().hex[:6]}"
            shutil.move(str(directory), str(trashed))
        self.session.delete(skill)
        self.session.commit()
        self.registry.reload()
        return trashed

    def edit_content(self, slug: str, content: str, note: str = "用户编辑") -> Skill:
        skill = self.session.scalar(select(Skill).where(Skill.slug == slug))
        if skill is None:
            raise NotFoundError(f"技能不存在: {slug}")
        meta, display_name, version, applies_to = self._parse_standard(content)
        directory = self._skill_dir(slug)
        if not directory.is_dir():
            raise ValidationError(f"技能目录不存在: {slug}")
        (directory / "SKILL.md").write_text(content, encoding="utf-8")
        new_version = f"{version}-{len(skill.versions) + 1}"
        skill.version = version
        skill.name = display_name
        skill.description = str(meta.get("description") or skill.description).strip()
        skill.applies_to = applies_to
        skill.versions.append(
            SkillVersion(version=new_version, content=content, note=note)
        )
        self.session.commit()
        self.registry.reload()
        return skill

    def rollback(self, slug: str, version_id: str) -> Skill:
        skill = self.session.scalar(select(Skill).where(Skill.slug == slug))
        if skill is None:
            raise NotFoundError(f"技能不存在: {slug}")
        version = self.session.get(SkillVersion, version_id)
        if version is None or version.skill_id != skill.id:
            raise NotFoundError("技能版本不存在")
        meta, display_name, skill_version, applies_to = self._parse_standard(version.content)
        path = self._skill_dir(slug) / "SKILL.md"
        path.write_text(version.content, encoding="utf-8")
        skill.name = display_name
        skill.version = skill_version
        skill.description = str(meta.get("description") or skill.description).strip()
        skill.applies_to = applies_to
        skill.versions.append(
            SkillVersion(
                version=f"{version.version}-rollback",
                content=version.content,
                note="回滚",
            )
        )
        self.session.commit()
        self.registry.reload()
        return skill


def default_skill_injection() -> SkillInjection:
    return SkillInjection(
        text=(
            "## 默认风格\n\n"
            "先给结论，再给证据；使用短句；每个论点配事实或案例；结尾给出可执行建议。"
        ),
        skills=[],
        degraded=[{"slug": "writing-style", "reason": "未绑定写作风格技能，使用默认风格"}],
    )
