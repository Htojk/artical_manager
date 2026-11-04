"""Skill registry with mtime-based hot reload."""

from __future__ import annotations

import threading
from pathlib import Path

from app.skills.loader import SkillInfo, SkillLoader


class SkillRegistry:
    def __init__(self, root: Path | str) -> None:
        self.loader = SkillLoader(root)
        self._cache: dict[str, tuple[float, SkillInfo]] = {}
        self._lock = threading.Lock()

    def reload(self) -> list[SkillInfo]:
        skills = self.loader.scan()
        with self._lock:
            self._cache = {
                skill.slug: (skill.mtime, skill) for skill in skills
            }
        return skills

    def get(self, slug: str) -> SkillInfo | None:
        with self._lock:
            cached = self._cache.get(slug)
        if cached is not None:
            current_mtime = self._current_mtime(cached[1])
            if current_mtime <= cached[0]:
                return cached[1]
        skill_dir = self.loader.root / slug
        if not skill_dir.is_dir():
            return None
        info = self.loader.load_directory(skill_dir)
        with self._lock:
            self._cache[slug] = (info.mtime, info)
        return info

    def available(self, stage: str | None = None) -> list[SkillInfo]:
        skills = self.reload()
        return [
            skill
            for skill in skills
            if skill.valid and (stage is None or stage in skill.applies_to)
        ]

    def invalid(self) -> list[SkillInfo]:
        return [skill for skill in self.reload() if not skill.valid]

    @staticmethod
    def _current_mtime(skill: SkillInfo) -> float:
        if skill.path is None:
            return 0.0
        try:
            files = [item for item in skill.path.rglob("*") if item.is_file()]
            return max((item.stat().st_mtime for item in files), default=0.0)
        except OSError:
            return 0.0
