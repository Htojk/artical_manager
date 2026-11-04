"""State graph wiring for the eight-stage article workflow."""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, StateGraph

from app.article_generation.workflow.nodes import WorkflowNodes
from app.article_generation.workflow.routing import (
    route_after_review,
    route_after_review_decision,
    route_after_stage,
    route_pause,
)
from app.article_generation.workflow.state import ArticleState

STAGE_ROUTES = {"continue": "continue", "pause": "pause", "halt": "halt"}
PAUSE_ROUTES = {
    "research": "research",
    "outline": "outline",
    "write": "write",
    "title": "title",
    "review": "review",
    "review_decision": "review_decision",
    "format": "format",
    "publish": "publish",
    "halt": "halt",
}


def build_graph(nodes: WorkflowNodes, checkpointer: Any):
    builder = StateGraph(ArticleState)
    builder.add_node("topic", nodes.topic)
    builder.add_node("research", nodes.research)
    builder.add_node("outline", nodes.outline)
    builder.add_node("write", nodes.write)
    builder.add_node("title", nodes.title)
    builder.add_node("review", nodes.review)
    builder.add_node("review_decision", nodes.review_decision)
    builder.add_node("format", nodes.format)
    builder.add_node("publish", nodes.publish)
    builder.add_node("pause", nodes.pause)
    builder.add_node("halt", nodes.halt)

    builder.set_entry_point("topic")
    for source, target in (
        ("topic", "research"),
        ("research", "outline"),
        ("outline", "write"),
        ("write", "title"),
        ("title", "review"),
    ):
        builder.add_conditional_edges(
            source,
            route_after_stage,
            {"continue": target, "pause": "pause", "halt": "halt"},
        )
    builder.add_conditional_edges(
        "review",
        route_after_review,
        {
            "format": "format",
            "research": "research",
            "outline": "outline",
            "write": "write",
            "review_decision": "review_decision",
            "pause": "pause",
            "halt": "halt",
        },
    )
    builder.add_conditional_edges(
        "review_decision",
        route_after_review_decision,
        {
            "format": "format",
            "research": "research",
            "outline": "outline",
            "write": "write",
        },
    )
    builder.add_conditional_edges(
        "format",
        route_after_stage,
        {"continue": "publish", "pause": "pause", "halt": "halt"},
    )
    builder.add_conditional_edges("pause", route_pause, PAUSE_ROUTES)
    builder.add_edge("publish", END)
    builder.add_edge("halt", END)
    return builder.compile(checkpointer=checkpointer)
