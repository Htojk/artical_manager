import type { VariantProps } from "class-variance-authority";
import { Badge, type badgeVariants } from "../ui/badge";
import {
  ARTICLE_STATUS_LABELS,
  PUBLISH_STATUS_LABELS,
  RUN_STATUS_LABELS,
  STAGE_STATUS_LABELS,
  SUGGESTION_STATUS_LABELS,
} from "../../lib/labels";
import type { ArticleStatus, RunStatus, StageStatus, SuggestionStatus } from "../../types";

type BadgeVariant = VariantProps<typeof badgeVariants>["variant"];

export type StatusKind = "article" | "run" | "stage" | "publish" | "suggestion";

interface StatusBadgeProps {
  kind: StatusKind;
  status: string;
  className?: string;
}

function variantFor(kind: StatusKind, status: string): BadgeVariant {
  if (kind === "stage") {
    if (status === "running") return "info";
    if (status === "completed") return "success";
    if (status === "failed") return "destructive";
    if (status === "warning") return "warning";
    return "secondary";
  }
  if (kind === "publish") {
    if (status === "published") return "success";
    if (status === "draft") return "info";
    if (status === "failed") return "destructive";
    if (status === "manual_required" || status === "unavailable") return "warning";
    if (status === "publishing" || status === "waiting_confirm") return "info";
    if (status === "offline") return "outline";
    return "secondary";
  }
  if (kind === "suggestion") {
    if (status === "applied") return "success";
    if (status === "approved") return "info";
    if (status === "rejected") return "destructive";
    if (status === "rolled_back") return "warning";
    return "secondary";
  }
  if (status === "published" || status === "completed") return "success";
  if (status === "failed") return "destructive";
  if (status === "running") return "info";
  if (
    status === "paused" ||
    status === "waiting_review" ||
    status === "waiting_publish" ||
    status === "waiting_topic" ||
    status === "needs_human"
  ) {
    return "warning";
  }
  return "secondary";
}

function labelFor(kind: StatusKind, status: string): string {
  if (kind === "article") {
    return ARTICLE_STATUS_LABELS[status as ArticleStatus] ?? status;
  }
  if (kind === "run") {
    return RUN_STATUS_LABELS[status as RunStatus] ?? status;
  }
  if (kind === "stage") {
    return STAGE_STATUS_LABELS[status as StageStatus | "warning"] ?? status;
  }
  if (kind === "suggestion") {
    return SUGGESTION_STATUS_LABELS[status as SuggestionStatus] ?? status;
  }
  return PUBLISH_STATUS_LABELS[status] ?? status;
}

export function StatusBadge({ kind, status, className }: StatusBadgeProps) {
  return (
    <Badge variant={variantFor(kind, status)} className={className}>
      <span className="h-1.5 w-1.5 rounded-full bg-current opacity-70" aria-hidden="true" />
      {labelFor(kind, status)}
    </Badge>
  );
}
