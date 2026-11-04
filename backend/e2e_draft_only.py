"""Generate one AI entertainment article through the real workflow; never publish it."""

from __future__ import annotations

import argparse
import sys
import time

from fastapi.testclient import TestClient

from app.main import create_app


def _json(response):
    if response.is_error:
        payload = response.json()
        raise RuntimeError(f"HTTP {response.status_code}: {payload.get('message', payload)}")
    return response.json()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--article-id", help="reuse an existing unselected article")
    parser.add_argument("--timeout", type=int, default=1200)
    parser.add_argument("--domain", default="AI 娱乐：人与 AI 的真实使用场景")
    parser.add_argument("--prefer-format", default="creative_experiment")
    args = parser.parse_args()

    with TestClient(create_app(start_scheduler=False)) as client:
        if args.article_id:
            article_id = args.article_id
            article = _json(client.get(f"/api/articles/{article_id}"))["article"]
            if not article["publish_confirmation"]:
                raise RuntimeError("拒绝运行：文章未启用发布前确认")
        else:
            created = _json(client.post("/api/articles", json={
                "topic_mode": "ai", "target_platforms": ["wechat"],
                "publish_confirmation": True,
            }))
            article_id = created["article"]["id"]
        print(f"ARTICLE_ID={article_id}", flush=True)

        topics = _json(client.post(
            f"/api/articles/{article_id}/topics/recommend",
            json={"domain": args.domain},
        ))["items"]
        if len(topics) != 5:
            raise RuntimeError(f"预期五个候选，实际 {len(topics)} 个")
        chosen = max(topics, key=lambda item: (
            item.get("content_format") == args.prefer_format,
            bool(item.get("hot_signals")),
            item.get("entertainment_score") or 0,
        ))
        print(f"TOPIC={chosen['title']}", flush=True)
        _json(client.post(f"/api/articles/{article_id}/topics/{chosen['id']}/select"))
        run = _json(client.post(f"/api/articles/{article_id}/run"))
        run_id = run["id"]
        print(f"RUN_ID={run_id}", flush=True)

        last_stage = None
        deadline = time.monotonic() + args.timeout
        while time.monotonic() < deadline:
            run = _json(client.get(f"/api/runs/{run_id}"))
            status = run["status"]
            stage = run.get("current_stage")
            if stage != last_stage:
                print(f"STAGE={stage} STATUS={status}", flush=True)
                last_stage = stage
            if status == "waiting_review":
                review = _json(client.get(f"/api/articles/{article_id}/stages/review"))
                report = review["content"].get("latest") or {}
                print(f"REVIEW={report.get('verdict')} SCORE={report.get('total')}", flush=True)
                if report.get("verdict") != "pass":
                    raise RuntimeError("审核未通过，保留草稿供人工检查")
                _json(client.post(f"/api/articles/{article_id}/review/decision",
                                  json={"decision": "approve", "feedback": ""}))
            elif status == "waiting_publish":
                writing = _json(client.get(f"/api/articles/{article_id}/stages/writing"))
                formatting = _json(client.get(f"/api/articles/{article_id}/stages/formatting"))
                draft = writing["content"].get("latest") or {}
                outputs = formatting["content"].get("outputs") or []
                records = _json(client.get(f"/api/articles/{article_id}/publish/records"))["items"]
                if not draft.get("content_md") or not outputs or records:
                    raise RuntimeError("草稿、排版或发布安全检查未通过")
                print(f"DONE words={draft.get('word_count')} formats={len(outputs)} published_records={len(records)}", flush=True)
                return 0
            elif status in {"failed", "needs_human", "cancelled", "completed"}:
                raise RuntimeError(f"工作流提前结束：{status}；{run.get('error') or ''}")
            time.sleep(5)
        raise TimeoutError("等待文章生成超时；未确认发布")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 - print a compact actionable error
        print(f"FAILED: {exc}", file=sys.stderr, flush=True)
        sys.exit(1)
