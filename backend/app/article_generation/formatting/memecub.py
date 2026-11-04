"""Choose and insert two licensed Memecub images into a Markdown article."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from html import escape
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, Field

from app.core.constants import Stage

logger = logging.getLogger(__name__)
SEARCH_URL = "https://memecub.com/api/v1/search"
FALLBACK_QUERIES = ("无语", "开心", "震惊", "思考")


class ImagePlacement(BaseModel):
    paragraph_index: int
    query: str = Field(min_length=1, max_length=20)


class ImagePlan(BaseModel):
    placements: list[ImagePlacement]


@dataclass(frozen=True)
class MemeImage:
    url: str
    title: str
    attribution: str


class MemecubClient:
    def __init__(self, api_key: str, *, timeout: float = 8.0,
                 transport: httpx.BaseTransport | None = None) -> None:
        self.api_key = api_key
        self.http = httpx.Client(timeout=timeout, transport=transport)

    def close(self) -> None:
        self.http.close()

    def search(self, query: str, *, commercial_only: bool = True) -> list[MemeImage]:
        response = self.http.get(
            SEARCH_URL,
            params={"q": query, "limit": 12, **({"commercial": 1} if commercial_only else {})},
            headers={"Authorization": f"Bearer {self.api_key}"},
        )
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("data", []) if isinstance(payload, dict) else []
        if not isinstance(rows, list):
            return []
        images: list[MemeImage] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            license_info = row.get("license") or {}
            if not isinstance(license_info, dict):
                continue
            if commercial_only and license_info.get("commercial_use") is not True:
                continue
            url = str(row.get("url") or "")
            parsed = urlparse(url)
            if (parsed.scheme != "https" or parsed.hostname != "gpic.code-nav.cn"
                    or parsed.username or parsed.password or parsed.port):
                continue
            attribution = str(row.get("attribution") or license_info.get("attribution") or "").strip()
            if license_info.get("attribution_required") and not attribution:
                continue
            images.append(MemeImage(url=url, title=str(row.get("title") or "表情包"),
                                    attribution=attribution))
        return images


def _eligible_paragraphs(blocks: list[str]) -> list[int]:
    eligible: list[int] = []
    in_fence = False
    for index, block in enumerate(blocks):
        stripped = block.strip()
        fence_count = sum(1 for line in stripped.splitlines()
                          if line.lstrip().startswith(("```", "~~~")))
        if in_fence or fence_count:
            if fence_count % 2:
                in_fence = not in_fence
            continue
        if not stripped or stripped.startswith(("#", ">", "- ", "* ", "|", "![", "<")):
            continue
        if re.match(r"\d+[.)]\s", stripped) or "![" in stripped:
            continue
        if len(stripped) >= 20:
            eligible.append(index)
    return eligible


def _fallback_plan(blocks: list[str], eligible: list[int]) -> list[ImagePlacement]:
    indices = [eligible[len(eligible) // 3], eligible[(len(eligible) * 2) // 3]]
    if indices[0] == indices[1]:
        indices = [eligible[0], eligible[-1]]
    return [ImagePlacement(paragraph_index=index, query=FALLBACK_QUERIES[position])
            for position, index in enumerate(indices)]


def _plan(blocks: list[str], eligible: list[int], llm: object | None,
          article_id: str) -> list[ImagePlacement]:
    if llm is None:
        return _fallback_plan(blocks, eligible)
    excerpts = "\n".join(f"{index}: {blocks[index][:180]}" for index in eligible[:35])
    try:
        result = llm.structured(
            stage=Stage.FORMATTING,
            schema=ImagePlan,
            system="你是娱乐类文章配图编辑。只为文章中确实有情绪转折或吐槽的两处选表情图，不改正文，不编造事实。",
            user=("从下列带编号的段落中选两处相隔至少一段的位置，每处给一个 2 到 8 字的"
                  "中文表情包搜索词。返回 placements，包含 paragraph_index 和 query。"
                  f"\n段落：\n{excerpts}"),
            article_id=article_id,
        )
        placements = result.placements
        indices = [item.paragraph_index for item in placements]
        if (len(placements) == 2 and len(set(indices)) == 2
                and all(index in eligible for index in indices)
                and abs(eligible.index(indices[0]) - eligible.index(indices[1])) >= 2):
            return sorted(placements, key=lambda item: item.paragraph_index)
    except Exception:  # noqa: BLE001 - model failure must not break formatting
        logger.warning("Memecub placement model unavailable; using fallback", exc_info=True)
    return _fallback_plan(blocks, eligible)


def enrich_markdown(content: str, *, article_id: str, client: MemecubClient,
                    llm: object | None = None, commercial_only: bool = True) -> tuple[str, str | None]:
    """Return unchanged content and a warning unless two usable images are available."""
    blocks = re.split(r"\n\s*\n", content)
    eligible = _eligible_paragraphs(blocks)
    if len(eligible) < 2:
        return content, "正文可插图的段落不足，未插入表情包"
    placements = _plan(blocks, eligible, llm, article_id)
    used: set[str] = set()
    selected: list[tuple[int, MemeImage]] = []
    for placement in placements:
        queries = (placement.query, *FALLBACK_QUERIES)
        for query in dict.fromkeys(queries):
            try:
                images = client.search(query, commercial_only=commercial_only)
            except (httpx.HTTPError, ValueError) as exc:
                logger.warning("Memecub search failed for %s: %s", query, exc)
                continue
            image = next((candidate for candidate in images if candidate.url not in used), None)
            if image is not None:
                used.add(image.url)
                selected.append((placement.paragraph_index, image))
                break
    if len(selected) != 2:
        return content, "Memecub 可用且授权合适的图片不足两张，未插入表情包"
    for index, item in selected:
        title = re.sub(r"[\[\]\\\n]", "", item.title).strip()[:60] or "表情包"
        url = item.url.replace("(", "%28").replace(")", "%29")
        block = f"![{title}]({url})"
        if item.attribution:
            block += f"\n\n<sub>图片来源：{escape(item.attribution)}</sub>"
        blocks[index] += "\n\n" + block
    return "\n\n".join(blocks), None
