"""Approve, apply, roll back evolution suggestions with snapshots and guardrails."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.constants import Stage, SuggestionStatus
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.models.evolution import EvolutionSuggestion
from app.models.llm import ModelProfile, StageModelBinding
from app.models.skill import Skill
from app.skills.manager import SkillManager
from app.skills.registry import SkillRegistry
from app.self_evolution.signals import SignalCollector, ArticleSignal

DEFAULT_RULE_SKILL = "evolution-writing-rules"

DEFAULT_RULE_SKILL_TEMPLATE = """---
name: 进化写作规则
description: 由自进化建议生成和维护的写作规则集合
version: 1.0.0
applies_to:
  - writing
entry: SKILL.md
---

# 进化写作规则

"""


class EvolutionApplier:
    def __init__(self, session: Session, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.skill_registry = SkillRegistry(self.settings.skills_dir)

    def _get(self, suggestion_id: str) -> EvolutionSuggestion:
        suggestion = self.session.get(EvolutionSuggestion, suggestion_id)
        if suggestion is None:
            raise NotFoundError("改进建议不存在")
        return suggestion

    def decide(
        self, suggestion_id: str, *, approve: bool, note: str = ""
    ) -> EvolutionSuggestion:
        suggestion = self._get(suggestion_id)
        if suggestion.status != SuggestionStatus.PENDING:
            raise ConflictError(f"建议当前状态为 {suggestion.status}，不能再次审批")
        suggestion.status = SuggestionStatus.APPROVED if approve else SuggestionStatus.REJECTED
        suggestion.decided_at = datetime.now(UTC)
        suggestion.decided_note = note
        self.session.commit()
        return suggestion

    def apply(self, suggestion_id: str) -> EvolutionSuggestion:
        suggestion = self._get(suggestion_id)
        if suggestion.status != SuggestionStatus.APPROVED:
            raise ConflictError("只有已批准的建议才能应用")
        baseline = self._baseline()
        snapshot, after = self._apply_patch(suggestion)
        suggestion.before_snapshot = snapshot
        suggestion.after_snapshot = after
        suggestion.baseline = baseline
        suggestion.status = SuggestionStatus.APPLIED
        suggestion.applied_at = datetime.now(UTC)
        self.session.commit()
        return suggestion

    def reject(self, suggestion_id: str, note: str = "") -> EvolutionSuggestion:
        suggestion = self._get(suggestion_id)
        if suggestion.status not in {SuggestionStatus.PENDING, SuggestionStatus.APPROVED}:
            raise ConflictError("当前状态不能拒绝")
        suggestion.status = SuggestionStatus.REJECTED
        suggestion.decided_note = note
        suggestion.decided_at = datetime.now(UTC)
        self.session.commit()
        return suggestion

    def rollback(self, suggestion_id: str) -> EvolutionSuggestion:
        suggestion = self._get(suggestion_id)
        if suggestion.status != SuggestionStatus.APPLIED:
            raise ConflictError("只有已应用的建议才能回滚")
        snapshot = suggestion.before_snapshot or {}
        kind = snapshot.get("kind")
        if kind in {"skill", "prompt"}:
            path = Path(snapshot["path"])
            content = snapshot.get("content")
            if content is None:
                if path.exists():
                    path.unlink()
            else:
                path.write_text(content, encoding="utf-8")
            if kind == "skill":
                self._sync_skills()
        elif kind == "model":
            binding = self.session.scalar(
                select(StageModelBinding).where(
                    StageModelBinding.stage == snapshot.get("stage")
                )
            )
            if snapshot.get("binding") is None:
                if binding is not None:
                    self.session.delete(binding)
            elif binding is None:
                self.session.add(StageModelBinding(**snapshot["binding"]))
            else:
                for key, value in snapshot["binding"].items():
                    if key != "id":
                        setattr(binding, key, value)
        suggestion.status = SuggestionStatus.ROLLED_BACK
        self.session.commit()
        return suggestion

    def refresh_effect(self, suggestion_id: str, *, window: int = 10) -> dict:
        suggestion = self._get(suggestion_id)
        if suggestion.status != SuggestionStatus.APPLIED:
            raise ConflictError("只有已应用的建议才能评估效果")
        current = self._baseline(window=window)
        baseline = suggestion.baseline or {}
        rollback_recommended = False
        if suggestion.type == "model_routing":
            current_score = current.get("average_review")
            base_score = baseline.get("average_review")
            if current_score is not None and (
                current_score < 70 or (base_score is not None and current_score < base_score - 5)
            ):
                rollback_recommended = True
        result = {
            "window": window,
            "baseline": baseline,
            "current": current,
            "rollback_recommended": rollback_recommended,
            "evaluated_at": datetime.now(UTC).isoformat(),
        }
        suggestion.result = result
        self.session.commit()
        return result

    def _baseline(self, window: int = 10) -> dict:
        signals: list[ArticleSignal] = SignalCollector(self.session).recent(limit=window)
        if not signals:
            return {"articles": 0}
        scores = [item.review_average for item in signals if item.review_average is not None]
        reworks = sum(1 for item in signals if item.rework_count > 0)
        costs = [item.cost for item in signals]
        return {
            "articles": len(signals),
            "average_review": round(sum(scores) / len(scores), 2) if scores else None,
            "rework_rate": round(reworks / len(signals), 3),
            "average_cost": round(sum(costs) / len(costs), 6),
        }

    def _apply_patch(self, suggestion: EvolutionSuggestion) -> tuple[dict, dict]:
        patch = suggestion.patch or {}
        if suggestion.type in {"skill_update", "writing_rule"}:
            slug = str(patch.get("slug") or (DEFAULT_RULE_SKILL if suggestion.type == "writing_rule" else "writing-style-tech-review"))
            return self._apply_skill(slug, patch, suggestion)
        if suggestion.type == "prompt_update":
            return self._apply_prompt(patch)
        if suggestion.type == "model_routing":
            return self._apply_model(patch, suggestion)
        raise ValidationError(f"不支持的建议类型: {suggestion.type}")

    def _apply_skill(self, slug: str, patch: dict, suggestion: EvolutionSuggestion) -> tuple[dict, dict]:
        if not slug or "/" in slug or "\\" in slug:
            raise ValidationError("技能 slug 无效")
        skill_dir = self.settings.skills_dir / slug
        skill_dir.mkdir(parents=True, exist_ok=True)
        path = skill_dir / "SKILL.md"
        before = path.read_text(encoding="utf-8") if path.exists() else None
        if patch.get("content"):
            after = str(patch["content"])
        else:
            append = str(patch.get("append") or suggestion.rationale or "")
            base = before or DEFAULT_RULE_SKILL_TEMPLATE
            after = base.rstrip() + "\n\n## 进化规则\n\n" + append.strip() + "\n"
        path.write_text(after, encoding="utf-8")
        self._sync_skills()
        return (
            {"kind": "skill", "slug": slug, "path": str(path), "content": before},
            {"kind": "skill", "slug": slug, "path": str(path), "content": after},
        )

    def _apply_prompt(self, patch: dict) -> tuple[dict, dict]:
        file_name = str(patch.get("file") or "")
        if not file_name or Path(file_name).name != file_name or not file_name.endswith(".md"):
            raise ValidationError("提示词文件名无效")
        path = (self.settings.prompts_dir / file_name).resolve()
        prompts_root = self.settings.prompts_dir.resolve()
        if not path.is_relative_to(prompts_root):
            raise ValidationError("提示词路径越界")
        before = path.read_text(encoding="utf-8") if path.exists() else None
        if patch.get("content"):
            after = str(patch["content"])
        else:
            append = str(patch.get("append") or "")
            if before is None and not append:
                raise ValidationError("提示词补丁缺少内容")
            after = (before or "") + ("\n\n" + append if append else "")
        path.write_text(after, encoding="utf-8")
        return (
            {"kind": "prompt", "path": str(path), "content": before},
            {"kind": "prompt", "path": str(path), "content": after},
        )

    def _apply_model(self, patch: dict, suggestion: EvolutionSuggestion) -> tuple[dict, dict]:
        stage = str(patch.get("stage") or suggestion.target_stage)
        binding = self.session.scalar(
            select(StageModelBinding).where(StageModelBinding.stage == stage)
        )
        profile = None
        if patch.get("model_profile_id"):
            profile = self.session.get(ModelProfile, patch["model_profile_id"])
        elif patch.get("model_name"):
            profile = self.session.scalar(
                select(ModelProfile).where(ModelProfile.name == patch["model_name"])
            )
        if profile is None:
            raise ValidationError("模型降级建议缺少有效模型")
        guardrail = float(patch.get("min_review_score", 70))
        if guardrail < 0 or guardrail > 100:
            raise ValidationError("质量保障阈值无效")
        before = (
            {
                "id": binding.id,
                "stage": binding.stage,
                "model_profile_id": binding.model_profile_id,
                "temperature": binding.temperature,
                "max_tokens": binding.max_tokens,
            }
            if binding
            else None
        )
        if binding is None:
            binding = StageModelBinding(
                stage=stage,
                model_profile_id=profile.id,
                temperature=float(patch.get("temperature", 0.7)),
                max_tokens=int(patch.get("max_tokens", 4096)),
            )
            self.session.add(binding)
        else:
            binding.model_profile_id = profile.id
            if "temperature" in patch:
                binding.temperature = float(patch["temperature"])
            if "max_tokens" in patch:
                binding.max_tokens = int(patch["max_tokens"])
        self.session.commit()
        after = {
            "id": binding.id,
            "stage": binding.stage,
            "model_profile_id": binding.model_profile_id,
            "temperature": binding.temperature,
            "max_tokens": binding.max_tokens,
        }
        return ({"kind": "model", "stage": stage, "binding": before}, {"kind": "model", "binding": after})

    def _sync_skills(self) -> None:
        self.skill_registry.reload()
        SkillManager(self.session, self.skill_registry).sync()
