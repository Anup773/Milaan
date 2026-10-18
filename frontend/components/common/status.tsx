import { Badge, type Tone } from "@/components/ui/badge";
import { humanise } from "@/lib/format";

const TONE_BY_STATUS: Record<string, Tone> = {
  // checks
  PASS: "pass",
  WARNING: "warn",
  ERROR: "fail",
  NOT_CHECKED: "neutral",
  // scenarios
  DRAFT: "neutral",
  SIMULATED: "info",
  REVIEW_REQUIRED: "warn",
  APPROVED: "pass",
  POSTED: "ledger",
  FINALIZED: "ledger",
  LOCKED: "ledger",
  REOPEN_REQUESTED: "warn",
  DISCARDED: "neutral",
  // adjustments
  REJECTED: "fail",
  // exceptions
  FLAGGED: "fail",
  UNDER_REVIEW: "info",
  EVIDENCE_REQUESTED: "warn",
  RETAINED: "neutral",
  CORRECTION_PENDING: "warn",
  RESOLVED: "pass",
  CLEARED: "neutral",
  // priority
  HIGH: "fail",
  MEDIUM: "warn",
  LOW: "neutral",
  // periods / files
  OPEN: "pass",
  PROCESSED: "pass",
  PENDING: "warn",
};

const LABELS: Record<string, string> = {
  FINALIZED: "Finalised",
  REVIEW_REQUIRED: "Needs review",
  NOT_CHECKED: "Not checked",
};

export function StatusBadge({ status }: { status: string | null | undefined }) {
  if (!status) return <Badge>-</Badge>;
  return <Badge tone={TONE_BY_STATUS[status] ?? "neutral"}>{LABELS[status] ?? humanise(status)}</Badge>;
}