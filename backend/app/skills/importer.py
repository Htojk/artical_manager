"""Safe extraction of Agent Skills ZIP packages.

The archive is untrusted: member names are normalised, dangerous entries are
rejected and every file is streamed into a staging directory with hard limits
instead of using ``ZipFile.extractall``.
"""

from __future__ import annotations

import io
import re
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from app.core.errors import PayloadTooLargeError, ValidationError

MANIFEST_NAME = "SKILL.md"
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_EXTRACTED_BYTES = 50 * 1024 * 1024
MAX_ARCHIVE_FILES = 500
CHUNK_SIZE = 64 * 1024

_SKIP_DIRS = {"__MACOSX"}
_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")


@dataclass(frozen=True)
class _Member:
    info: zipfile.ZipInfo
    parts: tuple[str, ...]


def decode_member_name(info: zipfile.ZipInfo) -> str:
    """Recover non-UTF-8 (typically GBK) filenames written by old ZIP tools."""
    if info.flag_bits & 0x800:
        return info.filename
    raw = info.filename.encode("cp437", errors="replace")
    for encoding in ("utf-8", "gbk"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return info.filename


def _normalize_parts(name: str) -> tuple[str, ...]:
    normalized = name.replace("\\", "/").strip()
    if not normalized or "\x00" in normalized:
        raise ValidationError("压缩包包含非法路径")
    if normalized.startswith("/") or _WINDOWS_DRIVE.match(normalized):
        raise ValidationError("压缩包包含绝对路径")
    parts = PurePosixPath(normalized).parts
    if ".." in parts:
        raise ValidationError("压缩包包含路径穿越")
    return tuple(part for part in parts if part not in ("", "."))


def _is_skipped(parts: tuple[str, ...]) -> bool:
    return any(part in _SKIP_DIRS or part.startswith(".") for part in parts)


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    file_type = (info.external_attr >> 16) & 0o170000
    return file_type == 0o120000


def _collect_members(archive: zipfile.ZipFile) -> list[_Member]:
    members: list[_Member] = []
    for info in archive.infolist():
        if info.is_dir():
            continue
        if info.flag_bits & 0x1:
            raise ValidationError("不支持加密的压缩包")
        if _is_symlink(info):
            raise ValidationError("压缩包包含符号链接")
        parts = _normalize_parts(decode_member_name(info))
        if not parts or _is_skipped(parts):
            continue
        members.append(_Member(info=info, parts=parts))
    if not members:
        raise ValidationError("压缩包中没有可用文件")
    if len(members) > MAX_ARCHIVE_FILES:
        raise PayloadTooLargeError(f"压缩包成员不能超过 {MAX_ARCHIVE_FILES} 个")
    return members


def _select_package_files(members: list[_Member]) -> tuple[list[tuple[zipfile.ZipInfo, tuple[str, ...]]], tuple[str, ...]]:
    manifests = [member for member in members if member.parts[-1].lower() == MANIFEST_NAME.lower()]
    if not manifests:
        raise ValidationError("压缩包中未找到 SKILL.md")
    if len(manifests) > 1:
        raise ValidationError("压缩包包含多个 SKILL.md，无法确定技能根目录")
    root_parts = manifests[0].parts[:-1]

    selected: list[tuple[zipfile.ZipInfo, tuple[str, ...]]] = []
    for member in members:
        if root_parts:
            if member.parts[: len(root_parts)] != root_parts:
                continue
            relative = member.parts[len(root_parts) :]
        else:
            relative = member.parts
        if not relative:
            continue
        if relative[-1].lower() == MANIFEST_NAME.lower():
            relative = (*relative[:-1], MANIFEST_NAME)
        selected.append((member.info, relative))
    return selected, root_parts


def extract_skill_zip(data: bytes, destination: Path | str) -> tuple[int, str]:
    """Extract a skill package into ``destination``.

    Returns ``(file_count, root_dir_hint)`` where the hint is the directory that
    originally wrapped ``SKILL.md`` (empty when the manifest was at the root).
    Raises ``ValidationError`` (422) or ``PayloadTooLargeError`` (413).
    """
    if len(data) > MAX_UPLOAD_BYTES:
        raise PayloadTooLargeError("ZIP 文件不能超过 20 MB")
    if not zipfile.is_zipfile(io.BytesIO(data)):
        raise ValidationError("不是有效的 ZIP 文件")

    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    root = destination.resolve()
    total = 0
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            members = _collect_members(archive)
            selected, root_parts = _select_package_files(members)
            if len(selected) > MAX_ARCHIVE_FILES:
                raise PayloadTooLargeError(f"压缩包成员不能超过 {MAX_ARCHIVE_FILES} 个")
            for info, relative in selected:
                target = destination.joinpath(*relative)
                resolved = target.resolve()
                if root not in resolved.parents:
                    raise ValidationError("压缩包包含路径穿越")
                resolved.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, resolved.open("wb") as sink:
                    while chunk := source.read(CHUNK_SIZE):
                        total += len(chunk)
                        if total > MAX_EXTRACTED_BYTES:
                            raise PayloadTooLargeError("解压后内容不能超过 50 MB")
                        sink.write(chunk)
    except zipfile.BadZipFile as exc:
        shutil.rmtree(destination, ignore_errors=True)
        raise ValidationError("ZIP 文件已损坏") from exc
    except (RuntimeError, NotImplementedError) as exc:
        shutil.rmtree(destination, ignore_errors=True)
        raise ValidationError(f"无法读取 ZIP 文件: {exc}") from exc
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise
    hint = root_parts[-1] if root_parts else ""
    return len(selected), hint
