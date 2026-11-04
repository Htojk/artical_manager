"""Skill discovery, hot reload and database binding tests."""

from __future__ import annotations

import io
import os
import time
import zipfile
from pathlib import Path

import pytest

from app.core.errors import (
    ConflictError,
    NotFoundError,
    PayloadTooLargeError,
    ValidationError,
)
from app.skills import importer
from app.skills.importer import decode_member_name, extract_skill_zip
from app.skills.loader import SkillLoader, parse_frontmatter
from app.skills.manager import SkillManager, default_skill_injection
from app.skills.registry import SkillRegistry

VALID = """---
name: 技术评论风格
description: 先结论后证据
version: 1.0.0
applies_to: [writing]
---

## 写作要求
先给结论，再给证据。
"""


MINIMAL_STANDARD = """---
name: minimal-skill
description: 最小标准技能
---

## 要求
保持简洁。
"""

STANDARD_METADATA = """---
name: tech-style
description: 面向工程读者的技术写作
license: MIT
compatibility: platform >= 1.0
allowed-tools: [Read, Grep]
metadata:
  display_name: 技术风格
---

## 正文
先给结论。
"""


def write_skill(root, slug, content=VALID, entry=None):
    directory = root / slug
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text(content, encoding="utf-8")
    if entry:
        (directory / entry).write_text("入口正文", encoding="utf-8")
    return directory


def test_parse_frontmatter_errors():
    meta, body = parse_frontmatter(VALID)
    assert meta["name"] == "技术评论风格"
    assert body.startswith("## 写作要求")
    with pytest.raises(ValueError):
        parse_frontmatter("no frontmatter")
    with pytest.raises(ValueError):
        parse_frontmatter("---\nname: x\n")


def test_loader_valid_and_invalid(tmp_path):
    write_skill(tmp_path, "good")
    write_skill(tmp_path, "bad", "---\nname: nope\n---\nbody")
    skills = {skill.slug: skill for skill in SkillLoader(tmp_path).scan()}
    assert skills["good"].valid
    assert skills["good"].applies_to == ["writing"]
    assert not skills["bad"].valid
    assert "必填字段" in skills["bad"].error


def test_loader_accepts_minimal_standard_skill(tmp_path):
    write_skill(tmp_path, "minimal-skill", MINIMAL_STANDARD)
    info = SkillLoader(tmp_path).load_directory(tmp_path / "minimal-skill")
    assert info.valid
    assert info.standard_name == "minimal-skill"
    assert info.name == "minimal-skill"
    assert info.version == "1.0.0"
    assert info.applies_to == []
    assert info.resources == []
    assert info.raw.startswith("---")
    assert "## 要求" in info.raw


def test_loader_reads_standard_metadata_and_display_name(tmp_path):
    write_skill(tmp_path, "tech-style", STANDARD_METADATA)
    info = SkillLoader(tmp_path).load_directory(tmp_path / "tech-style")
    assert info.valid
    assert info.standard_name == "tech-style"
    assert info.name == "技术风格"
    assert info.license == "MIT"
    assert info.compatibility == "platform >= 1.0"
    assert info.allowed_tools == ["Read", "Grep"]
    assert info.metadata["display_name"] == "技术风格"


def test_loader_display_name_falls_back_to_name(tmp_path):
    write_skill(tmp_path, "minimal-skill", MINIMAL_STANDARD)
    info = SkillLoader(tmp_path).load_directory(tmp_path / "minimal-skill")
    assert info.name == "minimal-skill"


def test_loader_rejects_missing_description_and_long_fields(tmp_path):
    write_skill(tmp_path, "bad", "---\nname: nope\n---\nbody")
    write_skill(tmp_path, "long-name", f"---\nname: {'a' * 65}\ndescription: d\n---\n")
    write_skill(
        tmp_path, "long-desc", f"---\nname: ok\ndescription: {'d' * 1025}\n---\n"
    )
    skills = {skill.slug: skill for skill in SkillLoader(tmp_path).scan()}
    assert not skills["bad"].valid
    assert "description" in skills["bad"].error
    assert not skills["long-name"].valid
    assert "64" in skills["long-name"].error
    assert not skills["long-desc"].valid
    assert "1024" in skills["long-desc"].error


def test_loader_missing_entry_is_invalid(tmp_path):
    (tmp_path / "empty").mkdir()
    info = SkillLoader(tmp_path).load_directory(tmp_path / "empty")
    assert not info.valid
    assert "SKILL.md" in info.error


def test_loader_lists_resources_without_injecting_them(tmp_path):
    directory = write_skill(tmp_path, "with-assets", MINIMAL_STANDARD)
    (directory / "references").mkdir()
    (directory / "references" / "checklist.md").write_text("check", encoding="utf-8")
    (directory / "scripts").mkdir()
    (directory / "scripts" / "run.py").write_text("print(1)", encoding="utf-8")
    (directory / "assets").mkdir()
    (directory / "assets" / ".hidden").write_text("hidden", encoding="utf-8")
    (directory / "notes.txt").write_text("not bundled", encoding="utf-8")

    info = SkillLoader(tmp_path).load_directory(directory)
    assert [item["path"] for item in info.resources] == [
        "references/checklist.md",
        "scripts/run.py",
    ]
    assert all(item["size"] > 0 for item in info.resources)
    assert "check" not in info.content


def test_builtin_skill_uses_standard_frontmatter():
    root = Path(__file__).resolve().parents[2]
    skills = {info.slug: info for info in SkillLoader(root / "skills").scan()}
    builtin = skills["writing-style-tech-review"]
    assert builtin.valid
    assert builtin.standard_name == "writing-style-tech-review"
    assert builtin.name == "科技评论文风"


def test_loader_custom_entry(tmp_path):
    content = VALID.replace("---\n\n##", "entry: STYLE.md\n---\n\n##", 1)
    directory = write_skill(tmp_path, "custom", content, entry="STYLE.md")
    info = SkillLoader(tmp_path).load_directory(directory)
    assert info.valid
    assert info.entry == "STYLE.md"
    assert info.content == "入口正文"


def test_registry_hot_reload(tmp_path):
    slug = "hot"
    write_skill(tmp_path, slug)
    registry = SkillRegistry(tmp_path)
    assert registry.get(slug).version == "1.0.0"
    time.sleep(0.01)
    (tmp_path / slug / "SKILL.md").write_text(
        VALID.replace("version: 1.0.0", "version: 2.0.0"), encoding="utf-8"
    )
    os.utime(tmp_path / slug / "SKILL.md", (time.time() + 2, time.time() + 2))
    assert registry.get(slug).version == "2.0.0"
    assert [item.slug for item in registry.available("writing")] == [slug]
    assert registry.available("review") == []


def test_manager_sync_bind_render(tmp_path, db_session):
    root = tmp_path / "skills"
    write_skill(root, "style")
    registry = SkillRegistry(root)
    manager = SkillManager(db_session, registry)
    skills = manager.sync()
    assert [skill.slug for skill in skills] == ["style"]

    binding = manager.bind("writing", "style", order=1)
    assert binding.stage == "writing"
    injection = manager.render_for_stage("writing")
    assert injection.skills[0]["slug"] == "style"
    assert "先给结论" in injection.text
    assert injection.degraded == []

    manager.set_enabled("style", False)
    degraded = manager.render_for_stage("writing")
    assert degraded.text == ""
    assert degraded.degraded[0]["reason"] == "技能已停用"

    manager.set_enabled("style", True)
    manager.unbind(binding.id)
    assert manager.render_for_stage("writing").skills == []


def test_manager_binds_any_prompt_stage(tmp_path, db_session):
    root = tmp_path / "skills"
    write_skill(root, "style")
    manager = SkillManager(db_session, SkillRegistry(root))
    manager.sync()

    binding = manager.bind("review", "style")
    assert binding.stage == "review"
    assert "先给结论" in manager.render_for_stage("review").text
    assert manager.render_for_stage("writing").skills == []

    for stage in ("formatting", "publishing"):
        with pytest.raises(ValidationError):
            manager.bind(stage, "style")
    with pytest.raises(NotFoundError):
        manager.bind("writing", "missing")


def test_manager_create_skill(tmp_path, db_session):
    root = tmp_path / "skills"
    root.mkdir()
    manager = SkillManager(db_session, SkillRegistry(root))

    skill = manager.create_skill(
        "data-story",
        description="用数据讲故事的写作规范",
        display_name="数据故事",
        content="## 要求\n每个结论配一个数字。",
        applies_to=["writing", "review"],
    )
    assert skill.slug == "data-story"
    assert skill.name == "数据故事"
    assert skill.version == "1.0.0"
    assert len(skill.versions) == 1
    text = (root / "data-story" / "SKILL.md").read_text(encoding="utf-8")
    assert "name: data-story" in text
    assert "display_name" in text
    info = manager.registry.get("data-story")
    assert info.valid
    assert info.name == "数据故事"
    assert "每个结论配一个数字" in info.content

    with pytest.raises(ConflictError):
        manager.create_skill("data-story", description="重复")
    with pytest.raises(ValidationError):
        manager.create_skill("Bad Slug", description="非法")
    with pytest.raises(ValidationError):
        manager.create_skill("empty-desc", description="  ")


def test_manager_exports_standard_zip_and_round_trips(tmp_path, db_session):
    root = tmp_path / "skills"
    directory = write_skill(root, "style", STANDARD_METADATA)
    (directory / "references").mkdir()
    (directory / "references" / "check.md").write_text("check", encoding="utf-8")
    (directory / ".DS_Store").write_text("junk", encoding="utf-8")
    manager = SkillManager(db_session, SkillRegistry(root))
    manager.sync()

    data = manager.export_skill("style")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        assert archive.namelist() == ["style/SKILL.md", "style/references/check.md"]
        manifest = archive.read("style/SKILL.md").decode("utf-8")
        assert "name: tech-style" in manifest
        assert "先给结论" in manifest

    other_root = tmp_path / "imported"
    other_root.mkdir()
    other = SkillManager(db_session, SkillRegistry(other_root))
    result = other.import_skill(data, filename="style.zip", slug="style-copy")
    assert result.skill.slug == "style-copy"
    info = other.registry.get("style-copy")
    assert info.valid
    assert info.standard_name == "tech-style"
    assert [item["path"] for item in info.resources] == ["references/check.md"]

    with pytest.raises(NotFoundError):
        manager.export_skill("missing")


def test_manager_delete_skill_moves_to_trash(tmp_path, db_session):
    root = tmp_path / "skills"
    trash = tmp_path / "trash"
    write_skill(root, "style")
    manager = SkillManager(db_session, SkillRegistry(root), trash_dir=trash)
    manager.sync()
    manager.bind("writing", "style")

    trashed = manager.delete_skill("style")
    assert trashed is not None and trashed.parent == trash
    assert not (root / "style").exists()
    assert (trashed / "SKILL.md").exists()
    assert manager.list_skills() == []
    assert manager.registry.get("style") is None
    assert manager.render_for_stage("writing").skills == []

    with pytest.raises(NotFoundError):
        manager.delete_skill("style")

    write_skill(root, "orphan", MINIMAL_STANDARD)
    manager.sync()
    (root / "orphan").rename(tmp_path / "removed-orphan")
    assert manager.delete_skill("orphan") is None
    assert manager.list_skills() == []

    with pytest.raises(ValidationError):
        manager._skill_dir("../escape")


def test_manager_system_prompt_only_injects_bound_stage(tmp_path, db_session):
    root = tmp_path / "skills"
    write_skill(root, "style")
    manager = SkillManager(db_session, SkillRegistry(root))
    manager.sync()
    manager.bind("review", "style", order=1)

    review_prompt = manager.system_prompt("review", "基础提示词")
    assert review_prompt.startswith("基础提示词")
    assert "本阶段技能要求" in review_prompt
    assert "先给结论" in review_prompt
    assert manager.system_prompt("outline", "基础提示词") == "基础提示词"


def test_manager_edit_and_rollback(tmp_path, db_session):
    root = tmp_path / "skills"
    write_skill(root, "style")
    manager = SkillManager(db_session, SkillRegistry(root))
    manager.sync()

    edited = VALID.replace("version: 1.0.0", "version: 1.1.0").replace(
        "先给结论，再给证据。", "先给结论，再给三条证据。"
    )
    skill = manager.edit_content("style", edited, note="test")
    assert skill.version == "1.1.0"
    assert (root / "style" / "SKILL.md").read_text(encoding="utf-8") == edited
    assert len(skill.versions) == 1

    version_id = skill.versions[0].id
    manager.rollback("style", version_id)
    assert "三条证据" in (root / "style" / "SKILL.md").read_text(encoding="utf-8")


def test_default_injection():
    injection = default_skill_injection()
    assert "默认风格" in injection.text
    assert injection.degraded


STANDARD_ZIP_SKILL = (
    "---\nname: data-story\ndescription: 用数据讲故事\n"
    "metadata:\n  display_name: 数据故事\n---\n\n## 要求\n每个结论配一个数字。\n"
)


def build_zip(entries: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def zip_manager(tmp_path, db_session) -> tuple[SkillManager, Path]:
    root = tmp_path / "skills"
    root.mkdir()
    return SkillManager(db_session, SkillRegistry(root)), root


def test_manager_imports_zip_package(tmp_path, db_session):
    manager, root = zip_manager(tmp_path, db_session)
    data = build_zip(
        {
            "data-story/SKILL.md": STANDARD_ZIP_SKILL,
            "data-story/references/check.md": "check",
            "data-story/scripts/run.py": "print(1)",
            "data-story/assets/logo.bin": "logo",
            "data-story/__MACOSX/._SKILL.md": "junk",
            "README.md": "outside root",
        }
    )

    result = manager.import_skill(data, filename="data-story.zip")

    assert result.skill.slug == "data-story"
    assert result.skill.name == "数据故事"
    assert result.imported_files == 4
    assert (root / "data-story" / "SKILL.md").read_text(encoding="utf-8") == STANDARD_ZIP_SKILL
    assert not (root / "data-story" / "data-story").exists()
    assert not (root / "data-story" / "README.md").exists()
    info = manager.registry.get("data-story")
    assert info.valid
    assert [item["path"] for item in info.resources] == [
        "assets/logo.bin",
        "references/check.md",
        "scripts/run.py",
    ]
    assert result.skill.versions[0].note == "导入 zip：data-story.zip"


def test_manager_imports_root_level_zip_and_derives_slug(tmp_path, db_session):
    manager, root = zip_manager(tmp_path, db_session)
    data = build_zip(
        {
            "SKILL.md": "---\nname: 根目录技能\ndescription: 根目录导入\n---\n\n正文\n",
            "references/note.md": "note",
        }
    )

    result = manager.import_skill(data, filename="My Skill.zip")

    assert result.skill.slug == "my-skill"
    assert (root / "my-skill" / "SKILL.md").exists()
    assert (root / "my-skill" / "references" / "note.md").exists()


def test_manager_import_normalizes_manifest_case(tmp_path, db_session):
    manager, root = zip_manager(tmp_path, db_session)
    data = build_zip(
        {
            "lower-skill/skill.md": STANDARD_ZIP_SKILL,
            "lower-skill/references/a.md": "a",
        }
    )

    result = manager.import_skill(data, filename="lower-skill.zip")

    assert result.skill.slug == "lower-skill"
    assert (root / "lower-skill" / "SKILL.md").exists()
    manifests = [
        path
        for path in (root / "lower-skill").iterdir()
        if path.name.lower() == "skill.md"
    ]
    assert len(manifests) == 1


def test_manager_import_uses_explicit_slug_and_rejects_uninferable(tmp_path, db_session):
    manager, root = zip_manager(tmp_path, db_session)
    chinese = build_zip({"中文技能/SKILL.md": STANDARD_ZIP_SKILL})

    with pytest.raises(ValidationError):
        manager.import_skill(chinese, filename="中文技能.zip")

    result = manager.import_skill(chinese, filename="中文技能.zip", slug="zh-skill")
    assert result.skill.slug == "zh-skill"
    assert (root / "zh-skill" / "SKILL.md").exists()

    with pytest.raises(ValidationError):
        manager.import_skill(chinese, filename="中文技能.zip", slug="Bad Slug")


def test_manager_import_rejects_unsafe_members(tmp_path, db_session):
    manager, root = zip_manager(tmp_path, db_session)

    for entry in ("../evil.md", "/etc/passwd", "C:/windows/evil.md"):
        data = build_zip({"SKILL.md": STANDARD_ZIP_SKILL, entry: "bad"})
        with pytest.raises(ValidationError):
            manager.import_skill(data, filename="unsafe.zip")
        assert not (root / "unsafe").exists()
        assert not (tmp_path / "evil.md").exists()

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("SKILL.md", STANDARD_ZIP_SKILL)
        link = zipfile.ZipInfo("link")
        link.external_attr = 0o120777 << 16
        archive.writestr(link, "target")
    with pytest.raises(ValidationError):
        manager.import_skill(buffer.getvalue(), filename="symlink.zip")


def test_manager_import_requires_single_manifest(tmp_path, db_session):
    manager, _ = zip_manager(tmp_path, db_session)

    with pytest.raises(ValidationError):
        manager.import_skill(
            build_zip({"references/a.md": "a"}), filename="missing.zip"
        )
    with pytest.raises(ValidationError):
        manager.import_skill(
            build_zip(
                {
                    "a/SKILL.md": STANDARD_ZIP_SKILL,
                    "b/SKILL.md": STANDARD_ZIP_SKILL,
                }
            ),
            filename="duplicate.zip",
        )


def test_manager_import_rejects_invalid_frontmatter_and_conflicts(tmp_path, db_session):
    manager, root = zip_manager(tmp_path, db_session)
    invalid = build_zip({"bad-skill/SKILL.md": "---\nname: bad-skill\n---\n\nbody"})

    with pytest.raises(ValidationError):
        manager.import_skill(invalid, filename="bad-skill.zip")
    assert not (root / "bad-skill").exists()
    assert manager.list_skills() == []

    valid = build_zip({"data-story/SKILL.md": STANDARD_ZIP_SKILL})
    manager.import_skill(valid, filename="data-story.zip")
    with pytest.raises(ConflictError):
        manager.import_skill(valid, filename="data-story.zip")
    # A rejected duplicate must not delete or move the pre-existing skill.
    assert [skill.slug for skill in manager.list_skills()] == ["data-story"]
    assert (root / "data-story" / "SKILL.md").exists()

    (root / "manual-skill").mkdir()
    (root / "manual-skill" / "SKILL.md").write_text(STANDARD_ZIP_SKILL, encoding="utf-8")
    with pytest.raises(ConflictError):
        manager.import_skill(valid, filename="data-story.zip", slug="manual-skill")


def test_manager_import_enforces_size_and_count_limits(tmp_path, db_session, monkeypatch):
    manager, root = zip_manager(tmp_path, db_session)
    data = build_zip(
        {"data-story/SKILL.md": STANDARD_ZIP_SKILL, "data-story/references/a.md": "a"}
    )

    monkeypatch.setattr(importer, "MAX_UPLOAD_BYTES", 10)
    with pytest.raises(PayloadTooLargeError):
        manager.import_skill(data, filename="data-story.zip")
    assert not (root / "data-story").exists()

    monkeypatch.setattr(importer, "MAX_UPLOAD_BYTES", 20 * 1024 * 1024)
    monkeypatch.setattr(importer, "MAX_EXTRACTED_BYTES", 10)
    with pytest.raises(PayloadTooLargeError):
        manager.import_skill(data, filename="data-story.zip")
    assert not (root / "data-story").exists()
    assert not list(root.glob(".import-*"))

    monkeypatch.setattr(importer, "MAX_EXTRACTED_BYTES", 50 * 1024 * 1024)
    monkeypatch.setattr(importer, "MAX_ARCHIVE_FILES", 1)
    with pytest.raises(PayloadTooLargeError):
        manager.import_skill(data, filename="data-story.zip")


def test_extract_rejects_non_zip_and_decodes_gbk_names(tmp_path):
    with pytest.raises(ValidationError):
        extract_skill_zip(b"not a zip", tmp_path / "stage")
    assert not (tmp_path / "stage").exists()

    raw = "references/中文.md".encode("gbk")
    info = zipfile.ZipInfo(raw.decode("cp437"))
    assert info.flag_bits & 0x800 == 0
    assert decode_member_name(info) == "references/中文.md"
