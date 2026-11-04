"""Generate reviewable evolution suggestions from signals."""

from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.constants import Stage, SuggestionStatus
from app.core.llm import LLMService
from app.core.prompts import PromptLoader
from app.models.evolution import EvolutionSuggestion
from app.models.llm import ModelProfile, StageModelBinding
from app.models.skill import Skill, SkillBinding
from app.schemas.artifacts import EvolvingSuggestions
from app.self_evolution.signals import SignalCollector

SYSTEM_PROMPT = "你是内容生产系统的改进分析师，只提出有证据、可验证、可回滚的建议。"
ALLOWED_TYPES = {"writing_rule", "skill_update", "prompt_update", "model_routing"}


@dataclass
class AnalyzeResult:
    suggestions: list[EvolutionSuggestion]


class EvolutionAnalyzer:
    def __init__(
        self,
        session: Session,
        llm: LLMService,
        *,
        prompts: PromptLoader | None = None,
        max_articles: int = 20,
    ) -> None:
        self.session = session
        self.llm = llm
        self.prompts = prompts or PromptLoader()
        self.max_articles = max_articles

    def current_config(self) -> dict:
        bindings = list(self.session.scalars(select(StageModelBinding)))
        profiles = [
            {
                "name": profile.name,
                "model": profile.model,
                "input_price": profile.input_price_per_1k,
                "output_price": profile.output_price_per_1k,
            }
            for profile in self.session.scalars(select(ModelProfile))
        ]
        skills = [
            {
                "slug": skill.slug,
                "name": skill.name,
                "version": skill.version,
                "stages": list(skill.applies_to or []),
            }
            for skill in self.session.scalars(select(Skill))
        ]
        bindings_payload = [
            {
                "stage": binding.stage,
                "model_profile_id": binding.model_profile_id,
                "temperature": binding.temperature,
                "max_tokens": binding.max_tokens,
            }
            for binding in bindings
        ]
        return {"model_profiles": profiles, "stage_bindings": bindings_payload, "skills": skills}

    def analyze(self, *, limit: int = 20) -> AnalyzeResult:
        signals = SignalCollector(self.session).recent(limit=min(limit, self.max_articles))
        if not signals:
            return AnalyzeResult(suggestions=[])
        prompt = self.prompts.render(
            "evolution.md",
            signals=json.dumps(
                [signal.as_dict() for signal in signals], ensure_ascii=False, indent=1
            ),
            current_config=json.dumps(self.current_config(), ensure_ascii=False, indent=1),
        )
        output = self.llm.structured(
            stage=Stage.EVOLUTION,
            schema=EvolvingSuggestions,
            system=SYSTEM_PROMPT,
            user=prompt,
        )
        created: list[EvolutionSuggestion] = []
        for suggestion in output.suggestions[:3]:
            if suggestion.type not in ALLOWED_TYPES:
                continue
            record = EvolutionSuggestion(
                type=suggestion.type,
                target_stage=suggestion.target_stage,
                title=suggestion.title,
                rationale=suggestion.rationale,
                evidence=[{"note": item} for item in suggestion.evidence],
                patch=suggestion.patch,
                expected_impact=suggestion.expected_impact,
                status=SuggestionStatus.PENDING,
            )
            self.session.add(record)
            created.append(record)
        self.session.commit()
        return AnalyzeResult(suggestions=created)

    def list_suggestions(self, status: str | None = None) -> list[EvolutionSuggestion]:
        query = select(EvolutionSuggestion).order_by(EvolutionSuggestion.created_at.desc())
        if status:
            query = query.where(EvolutionSuggestion.status == status)
        return list(self.session.scalars(query))
