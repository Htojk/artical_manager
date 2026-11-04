"""Build a standard Agent Skills ZIP package from a skill directory."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

from app.core.errors import ValidationError

MANIFEST_NAME = "SKILL.md"


def build_skill_zip(skill_dir: Path | str, slug: str) -> bytes:
    """Zip ``skill_dir`` as ``<slug>/SKILL.md`` plus every bundled resource."""
    root = Path(skill_dir).resolve()
    if not root.is_dir() or not (root / MANIFEST_NAME).is_file():
        raise ValidationError(f"技能目录缺少 {MANIFEST_NAME}: {slug}")

    files: list[tuple[str, Path]] = []
    for item in root.rglob("*"):
        if not item.is_file() or item.is_symlink():
            continue
        try:
            relative = item.resolve().relative_to(root)
        except (OSError, ValueError):
            continue
        if any(part.startswith(".") for part in relative.parts):
            continue
        files.append((relative.as_posix(), item))
    files.sort(key=lambda pair: pair[0])

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for relative, item in files:
            archive.write(item, arcname=f"{slug}/{relative}")
    return buffer.getvalue()
