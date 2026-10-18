// Shapes of what the Milaan API returns. Written from the API's real responses (money is always an exact
// decimal string; dates are "YYYY-MM-DD"; moments are "YYYY-MM-DD HH:MM:SS.ffffff+00:00").

import type { Role } from "./roles";

export interface Me {
  userId: string;
  firmId: string;
  role: Role;
  email: string | null;
}

export interface Company {
  id: string;
  name: string;
  created_at: string;
}

export type LockStatus = "OPEN" | "LOCKED";

export interface Period {
  id: string;
  label: string;
  period_start: string;
  period_end: string;
  lock_status: LockStatus;
}

export interface Account {
  id: string;
  code: string;
  name: string;
  account_type: "Asset" | "Liability" | "Equity" | "Income" | "Expense";
  parent_account_id: string | null;
}

export interface Person {
  email: string | null;
  role: string;
}

/** Ids -> who they are, as several endpoints return it. */
export type People = Record<string, Person>;

// ── statements ─────────────────────────────────────────────────────────────
export interface TrialBalanceLine {
  account_id: string;
  code: string;
  name: string;
  account_type: string;
  total_debit: string;
  total_credit: string;
  balance: string;
}

export interface TrialBalance {
  period_id: string;
  period_label: string;
  period_start: string;
  period_end: string;
  lines: TrialBalanceLine[];
  total_debit: string;
  total_credit: string;
}

export interface ProfitLoss {
  period_id: string;
  period_label: string;
  period_start: string;
  period_end: string;
  income: TrialBalanceLine[];
  expense: TrialBalanceLine[];
  total_income: string;
  total_expense: string;
  net_profit: string;
}

export interface BalanceSheetLine {
  account_id: string;
  code: string;
  name: string;
  balance: string;
}

export interface BalanceSheet {
  as_of_date: string;
  assets: BalanceSheetLine[];
  liabilities: BalanceSheetLine[];
  equity: BalanceSheetLine[];
  retained_earnings: string;
  total_assets: string;
  total_liabilities: string;
  total_equity_and_retained_earnings: string;
  balances: boolean;
}

export interface CashFlow {
  period_id: string;
  period_label: string;
  period_start: string;
  period_end: string;
  cash_accounts: Array<{ account_id?: string; code?: string; name?: string; net_movement?: string; [key: string]: unknown }>;
  net_cash_flow: string;
  note?: string;
}

export interface GeneralLedger {
  account_id: string;
  code: string;
  name: string;
  account_type: string;
  period_id: string;
  period_label: string;
  period_start: string;
  period_end: string;
  opening_balance: string;
  lines: Array<{
    entry_date: string;
    description: string;
    debit: string;
    credit: string;
    journal_entry_id: string;
    running_balance: string;
  }>;
  closing_balance: string;
}

// ── drill-down ─────────────────────────────────────────────────────────────
export interface TraceOrigin {
  type: string;
  source_file_id?: string;
  filename?: string;
  row_number?: number;
  adjustment_id?: string;
  [key: string]: unknown;
}

export interface TraceLine {
  journal_entry_id: string;
  entry_date: string;
  description: string;
  debit: string;
  credit: string;
  origin: TraceOrigin | null;
}

export interface Trace {
  account_id: string;
  code: string;
  name: string;
  account_type: string;
  period_id: string;
  period_label: string;
  scope: "period" | "cumulative";
  lines: TraceLine[];
}

// ── dependency graph / impact ──────────────────────────────────────────────
export interface GraphNode {
  id: string;
  label: string;
  kind: "ledger" | "statement" | string;
  is_leaf: boolean;
  formula: string | null;
  value: string;
  meta: Record<string, unknown>;
}

export interface Graph {
  nodes: GraphNode[];
  edges: Array<{ from: string; to: string }>;
}

export interface ImpactRow {
  node: string;
  label: string;
  current: string;
  scenario: string;
  delta: string;
  pct_change: string | null;
}

export interface ImpactReport {
  summary: {
    headline: string;
    nothing_changes: boolean;
    figures_changed: number;
    accounts_affected: number;
    statement_lines_affected: number;
    balanced_after: boolean;
  };
  sources: ImpactRow[];
  profit_and_loss: ImpactRow[];
  balance_sheet: ImpactRow[];
  checks: ImpactRow & { balanced_before: boolean; balanced_after: boolean };
  accounts: Array<ImpactRow & { code: string; name: string; account_type: string; scope: string }>;
  flow: Array<{ node: string; label: string; kind: string; delta: string }>;
}

export interface ImpactPreview {
  period_id: string;
  basis: string;
  note: string;
  report: ImpactReport;
}

export interface ScenarioImpact {
  scenario_id: string;
  title: string;
  version: number;
  status: string;
  period_id: string;
  simulated_at: string | null;
  basis: string;
  note: string;
  simulation_current: boolean;
  report: ImpactReport;
}

// ── scenarios ──────────────────────────────────────────────────────────────
export type ScenarioStatus =
  | "DRAFT"
  | "SIMULATED"
  | "REVIEW_REQUIRED"
  | "APPROVED"
  | "POSTED"
  | "FINALIZED"
  | "LOCKED"
  | "REOPEN_REQUESTED"
  | "DISCARDED";

export interface ScenarioListItem {
  scenario_id: string;
  period_id: string;
  title: string;
  version: number;
  status: ScenarioStatus;
  superseded_by: string | null;
  created_by: string;
  created_at: string;
}

export interface ScenarioTransition {
  action: string;
  from_status: string | null;
  to_status: string;
  actor_id: string | null;
  note: string | null;
  at: string;
}

export interface Scenario {
  id: string;
  company_id: string;
  accounting_period_id: string;
  title: string;
  description: string;
  version: number;
  supersedes_id: string | null;
  superseded_by: string | null;
  status: ScenarioStatus;
  overrides: Record<string, string>;
  simulation: Record<string, unknown> | null;
  simulated_at: string | null;
  created_by: string;
  reviewed_by: string | null;
  reviewed_at: string | null;
  review_note: string | null;
  finalized_by: string | null;
  finalized_at: string | null;
  reopen_requested_by: string | null;
  reopen_reason: string | null;
  reopen_requested_at: string | null;
  reopen_decided_by: string | null;
  reopen_decided_at: string | null;
  created_at: string;
  updated_at: string;
  transitions: ScenarioTransition[];
  linked_adjustments: Array<Record<string, unknown>>;
  period_lock_status: LockStatus;
  available_actions: string[];
}

// ── adjustments ────────────────────────────────────────────────────────────
export type AdjustmentStatus = "REVIEW_REQUIRED" | "POSTED" | "REJECTED" | string;

export interface Adjustment {
  id: string;
  accounting_period_id: string;
  entry_date: string;
  description: string;
  reason: string;
  status: AdjustmentStatus;
  proposed_by: string;
  reviewed_by: string | null;
  reviewed_at: string | null;
  rejection_note: string | null;
  journal_entry_id: string | null;
  created_at: string;
}

export interface AdjustmentDetail extends Adjustment {
  lines: Array<{ account_id: string; debit: string; credit: string }>;
}

// ── schedules ──────────────────────────────────────────────────────────────
export interface FixedAsset {
  id: string;
  name: string;
  acquisition_date: string;
  cost: string;
  salvage_value: string;
  useful_life_months: number;
  depreciation_method: string;
  asset_account_id: string;
  accumulated_depreciation_account_id: string;
  depreciation_expense_account_id: string;
  disposed_date: string | null;
}

export interface Rollforward {
  period_id: string;
  period_start: string;
  period_end: string;
  assets: Array<{
    fixed_asset_id: string;
    name: string;
    cost: string;
    accumulated_before_period: string;
    opening_wdv: string;
    depreciation_this_period: string;
    closing_wdv: string;
  }>;
}

export interface ScheduleReconcile {
  period_id: string;
  as_of: string;
  assets: Array<{
    fixed_asset_id: string;
    name: string;
    schedule_accumulated_depreciation: string;
    assets_sharing_account: number;
    account_schedule_total: string;
    ledger_accumulated_depreciation_account_balance: string;
    matches: boolean;
  }>;
}

// ── imports & mappings ─────────────────────────────────────────────────────
export interface ImportIssue {
  row: number;
  field: string;
  severity: string;
  message: string;
}

export interface ImportResult {
  sourceFileId: string;
  rows: number;
  errors: number;
  warnings: number;
  total_debit: string;
  total_credit: string;
  issues_total: number;
  issues: ImportIssue[];
}

export interface UnmappedAccount {
  account_ref_key: string;
  sample_text: string;
  row_count: number;
  first_row_number: number;
}

export interface MaterializeResult {
  posted: number;
  already_posted: number;
  blocked: Array<Record<string, unknown>>;
  skipped: Array<Record<string, unknown>>;
  posted_with_warnings: Array<Record<string, unknown>>;
}

export interface SourceFile {
  id: string;
  filename: string;
  uploaded_at: string;
  status: string;
  uploaded_by: string | null;
  rows: number;
  rows_with_errors: number;
  rows_with_warnings: number;
  total_debit: string;
  total_credit: string;
  first_date: string | null;
  last_date: string | null;
  rows_posted_to_ledger: number;
}

// ── versions ───────────────────────────────────────────────────────────────
export interface VersionRowSide {
  id: string;
  row_number: number;
  account_ref: string;
  transaction_date: string | null;
  description: string;
  debit: string;
  credit: string;
  reference: string | null;
  status: string;
}

export interface VersionChange {
  kind: "CHANGED" | "ADDED" | "REMOVED" | "UNCHANGED";
  matched_by?: string;
  old: VersionRowSide | null;
  new: VersionRowSide | null;
  fields?: Array<{ field: string; old: string | null; new: string | null }>;
  old_posted?: boolean;
  new_posted?: boolean;
}

export interface VersionCompare {
  base: SourceFile;
  compare: SourceFile;
  summary: {
    base_rows: number;
    compare_rows: number;
    unchanged: number;
    changed: number;
    added: number;
    removed: number;
    already_posted_changes: number;
    posted_in_both: number;
  };
  totals: {
    base: { rows: number; total_debit: string; total_credit: string; in_balance: boolean };
    compare: { rows: number; total_debit: string; total_credit: string; in_balance: boolean };
    delta_debit: string;
    delta_credit: string;
  };
  by_account: Array<{
    account_key: string;
    label: string;
    account: { id: string; code: string; name: string; account_type: string } | null;
    base_debit: string;
    base_credit: string;
    compare_debit: string;
    compare_credit: string;
    changed_rows: number;
    net_change: string;
  }>;
  by_period: Array<{
    period_id: string;
    label: string;
    start: string;
    end: string;
    locked: boolean;
    base_debit: string;
    base_credit: string;
    compare_debit: string;
    compare_credit: string;
    changed_rows: number;
    net_change: string;
    affected: boolean;
  }>;
  locked_periods_affected: Array<{ period_id: string; label: string }>;
  warnings: string[];
  changes: VersionChange[];
  changes_total: number;
  limit: number;
  offset: number;
}

// ── reconciliation ─────────────────────────────────────────────────────────
export type CheckStatus = "PASS" | "WARNING" | "ERROR" | "NOT_CHECKED";

export interface ReconResult {
  rule_id: string;
  title: string;
  status: CheckStatus;
  message: string;
  details?: Record<string, unknown>;
}

export interface ReconRun {
  run_id: string;
  run_at: string;
  scenario_id: string | null;
  with_overrides: boolean;
  overall_status: CheckStatus;
  counts: Record<CheckStatus, number>;
  results: ReconResult[];
  period_id?: string;
  run_by?: string;
}

export interface ReconRunSummary {
  run_id: string;
  scenario_id: string | null;
  with_overrides: boolean;
  run_by: string | null;
  run_at: string;
  overall_status: CheckStatus;
  counts: Record<CheckStatus, number>;
}

// ── exceptions ─────────────────────────────────────────────────────────────
export type ExceptionStatus =
  | "FLAGGED"
  | "UNDER_REVIEW"
  | "EVIDENCE_REQUESTED"
  | "RETAINED"
  | "CORRECTION_PENDING"
  | "RESOLVED"
  | "CLEARED";

export interface ExceptionListItem {
  id: string;
  accounting_period_id: string;
  rule_id: string;
  category: string;
  source: string;
  title: string;
  message: string;
  priority: "LOW" | "MEDIUM" | "HIGH";
  journal_entry_id: string | null;
  amount: string | null;
  status: ExceptionStatus;
  assigned_to: string | null;
  decision: string | null;
  created_at: string;
}

export interface ExceptionDetail extends ExceptionListItem {
  company_id: string;
  fingerprint: string;
  related_entry_ids: string[];
  details: Record<string, unknown>;
  detected_run_id: string | null;
  raised_by: string | null;
  decision_note: string | null;
  decided_by: string | null;
  decided_at: string | null;
  updated_at: string;
  transitions: Array<{
    action: string;
    from_status: string | null;
    to_status: string;
    actor_id: string | null;
    note: string | null;
    run_id: string | null;
    at: string;
  }>;
  linked_adjustments: Array<Record<string, unknown>>;
  entries: Array<{
    journal_entry_id: string;
    entry_date: string;
    description: string;
    period_id: string;
    lines: Array<{ code: string; name: string; account_type: string; debit: string; credit: string }>;
  }>;
  period_lock_status: LockStatus;
  available_actions: string[];
}

export interface ExceptionSummary {
  period_id: string | null;
  open_total: number;
  by_status: Record<string, number>;
  open_by_category: Record<string, number>;
  open_by_priority: Record<string, number>;
  last_run: { run_id: string; run_at: string; run_by: string; counts: Record<string, number> } | null;
}

export interface DetectionRun {
  run_id: string;
  run_at: string;
  period_id: string;
  counts: {
    findings: number;
    new: number;
    redetected: number;
    already_known: number;
    cleared: number;
    open_after: number;
  };
  rules: Array<{
    rule_id: string;
    category: string;
    title: string;
    status: string;
    message: string;
    findings: number;
  }>;
}

// ── approvals ──────────────────────────────────────────────────────────────
export type ApprovalKind = "scenario_review" | "finalization" | "reopen_request" | "adjustment";

export interface ApprovalItem {
  kind: ApprovalKind;
  id: string;
  title: string;
  period_id: string;
  period_label: string;
  period_locked: boolean;
  made_by: string | null;
  note: string | null;
  amount: string | null;
  label: string;
  waiting_since: string;
  waiting_days: number;
  is_mine: boolean;
  can_decide: boolean;
  decisions: Record<string, { allowed: boolean; reasons: string[] }>;
  decide_via: { method: string; path: string };
}

export interface ApprovalInbox {
  items: ApprovalItem[];
  count: number;
  people: People;
  actor: { id: string; role: string };
}

export interface ApprovalSummary {
  period_id: string | null;
  waiting_total: number;
  waiting_by_kind: Record<ApprovalKind, number>;
  waiting_for_you: number;
  waiting_on_others: number;
  oldest_waiting_days: number;
  decided: {
    total_by_outcome: Record<string, number>;
    by_kind: Record<string, Record<string, number>>;
  };
}

export interface ApprovalHistory {
  decisions: Array<{
    at: string;
    kind: ApprovalKind;
    outcome: string;
    object_id: string;
    title: string;
    period_id: string;
    period_label: string;
    decided_by: string | null;
    made_by: string | null;
    note: string | null;
    amount: string | null;
  }>;
  has_more: boolean;
  limit: number;
  offset: number;
  people: People;
}

export interface ApprovalDetail {
  [key: string]: unknown;
}

// ── audit ──────────────────────────────────────────────────────────────────
export interface AuditEvent {
  id: string;
  seq: number;
  occurred_at: string;
  actor_id: string | null;
  action: string;
  object_type: string;
  object_id: string;
  period_id: string | null;
  old_value: Record<string, unknown> | null;
  new_value: Record<string, unknown> | null;
  reason: string | null;
  prev_hash: string;
  event_hash: string;
  action_label: string;
  object_label: string;
  changes: Array<{ field: string; old: unknown; new: unknown }>;
  actor: Person | null;
  headline: string;
}

export interface AuditList {
  events: AuditEvent[];
  total: number;
  has_more: boolean;
  limit: number;
  offset: number;
  filters: Record<string, unknown>;
}

export interface AuditEventDetail extends AuditEvent {
  previous: AuditEvent | null;
  next: AuditEvent | null;
}

export interface AuditSummary {
  total: number;
  first_event_at: string | null;
  last_event_at: string | null;
  latest_seq: number;
  by_group: Array<{ group: string; count: number }>;
  by_object_type: Array<{ object_type: string; label: string; count: number }>;
  by_actor: Array<{ actor_id: string | null; actor: Person | null; count: number; last_event_at: string }>;
}

export interface AuditVerify {
  ok: boolean;
  events_checked: number;
  first_broken_seq: number | null;
  problem: string | null;
  head_seq: number;
  head_hash: string | null;
  head_at: string | null;
  checked_at: string;
}

export interface AuditCatalog {
  actions: Array<{ action: string; label: string }>;
  action_groups: string[];
  object_types: Array<{ object_type: string; label: string }>;
  roles: { read: string[]; export: string[]; verify: string[] };
  limits: { default_limit: number; max_limit: number; max_export_rows: number };
}