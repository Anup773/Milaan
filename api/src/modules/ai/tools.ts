/**
 * What the assistant may look at. Every tool is a fixed, read-only request to one of the API's own routes, made
 * with the signed-in person's own token, so the person's role, firm and company limits apply exactly as on the
 * screens. The model supplies only the arguments listed in each tool's schema (ids, a period, a filter); it never
 * chooses a URL, a method or a company.
 *
 * There is no tool that posts, approves, finalises, adds or changes anything. The one POST ("what_if") is the
 * engine's what-if calculation, which saves nothing.
 */

export class ToolInputError extends Error {}

export interface ToolRequest {
  method: "GET" | "POST";
  path: string; // always starts with /companies/<companyId>/
  query?: Record<string, string>;
  body?: unknown;
}

export interface JsonSchema {
  type: "object";
  properties: Record<string, unknown>;
  required?: string[];
}

export interface DescribeContext {
  periodLabel: (periodId: string) => string;
}

export interface ToolDef {
  name: string;
  description: string;
  input_schema: JsonSchema;
  /** The screen where the person can see the same thing. */
  page: string;
  build(input: Record<string, unknown>, companyId: string): ToolRequest;
  describe(input: Record<string, unknown>, ctx: DescribeContext): string;
  /** Re-arranges a result into a smaller shape. Never computes, rounds or drops a figure that stays. */
  shape?(data: unknown): unknown;
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const AMOUNT = /^-?\d{1,15}(\.\d{1,2})?$/;

function uuid(input: Record<string, unknown>, key: string, required: true): string;
function uuid(input: Record<string, unknown>, key: string, required: false): string | undefined;
function uuid(input: Record<string, unknown>, key: string, required: boolean): string | undefined {
  const v = input[key];
  if (v === undefined || v === null || v === "") {
    if (required) throw new ToolInputError(`${key} is required`);
    return undefined;
  }
  if (typeof v !== "string" || !UUID.test(v)) throw new ToolInputError(`${key} must be an id exactly as returned by another tool`);
  return v.toLowerCase();
}

function oneOf(input: Record<string, unknown>, key: string, allowed: readonly string[]): string | undefined {
  const v = input[key];
  if (v === undefined || v === null || v === "") return undefined;
  if (typeof v !== "string" || !allowed.includes(v)) throw new ToolInputError(`${key} must be one of: ${allowed.join(", ")}`);
  return v;
}

function intIn(input: Record<string, unknown>, key: string, min: number, max: number): number | undefined {
  const v = input[key];
  if (v === undefined || v === null || v === "") return undefined;
  if (typeof v !== "number" || !Number.isInteger(v) || v < min || v > max) throw new ToolInputError(`${key} must be a whole number from ${min} to ${max}`);
  return v;
}

const opt = (key: string, value: string | undefined): Record<string, string> => (value ? { [key]: value } : {});
const base = (companyId: string) => `/companies/${companyId}`;
const period = { type: "string", description: "Accounting period id, from list_periods." };
const accountId = { type: "string", description: "Account id, from list_accounts or ledger_balances." };
const ofPeriod = (ctx: DescribeContext, input: Record<string, unknown>) => ctx.periodLabel(String(input.periodId ?? ""));

function periodTool(name: string, description: string, route: string, page: string, label: string, extra?: Partial<ToolDef>): ToolDef {
  return {
    name,
    description,
    input_schema: { type: "object", properties: { periodId: period }, required: ["periodId"] },
    page,
    build: (input, companyId) => ({ method: "GET", path: `${base(companyId)}/${route}`, query: { periodId: uuid(input, "periodId", true) } }),
    describe: (input, ctx) => `${label}, ${ofPeriod(ctx, input)}`,
    ...extra,
  };
}

// The values the engine itself uses (engine/exceptions/state_machine.py, scenarios/state_machine.py, adjustments/cli.py).
const FLAG_STATUSES = ["FLAGGED", "UNDER_REVIEW", "EVIDENCE_REQUESTED", "RETAINED", "CORRECTION_PENDING", "RESOLVED", "CLEARED"] as const;
const FLAG_CATEGORIES = ["DUPLICATE_INVOICE", "DUPLICATE_AMOUNT", "MISSING_EVIDENCE", "VENDOR_MISMATCH", "UNUSUAL_TRANSACTION", "PERIOD_CUTOFF", "UNSUPPORTED_EXPENSE", "OTHER"] as const;
const FLAG_PRIORITIES = ["LOW", "MEDIUM", "HIGH"] as const;
const SCENARIO_STATUSES = ["DRAFT", "SIMULATED", "REVIEW_REQUIRED", "APPROVED", "POSTED", "FINALIZED", "LOCKED", "REOPEN_REQUESTED", "DISCARDED"] as const;
const ADJUSTMENT_STATUSES = ["REVIEW_REQUIRED", "POSTED", "REJECTED"] as const;

export const TOOLS: ToolDef[] = [
  {
    name: "list_periods",
    description: "The company's accounting periods with their ids, dates and lock status. Use it first to find the period a question is about.",
    input_schema: { type: "object", properties: {} },
    page: "/dashboard",
    build: (_i, c) => ({ method: "GET", path: `${base(c)}/accounting-periods` }),
    describe: () => "Accounting periods",
  },
  {
    name: "list_accounts",
    description: "The chart of accounts: id, code, name and type (Asset, Liability, Equity, Income, Expense) of every account. Use it to find an account's id from its name.",
    input_schema: { type: "object", properties: {} },
    page: "/mappings",
    build: (_i, c) => ({ method: "GET", path: `${base(c)}/accounts` }),
    describe: () => "Chart of accounts",
    shape: (data) => {
      const rows = (data as { accounts?: Array<Record<string, unknown>> })?.accounts;
      if (!Array.isArray(rows)) return data;
      return { accounts: rows.map((a) => ({ id: a.id, code: a.code, name: a.name, type: a.account_type })) };
    },
  },
  periodTool("trial_balance", "The trial balance for a period: every account's debit and credit totals.", "statements/trial-balance", "/statements", "Trial balance"),
  periodTool("profit_loss", "The profit and loss statement for a period: income, expense and net profit.", "statements/profit-loss", "/statements", "Profit and loss"),
  periodTool("balance_sheet", "The balance sheet as at the end of a period: assets, liabilities, equity.", "statements/balance-sheet", "/statements", "Balance sheet"),
  periodTool("cash_flow", "The cash flow statement for a period.", "statements/cash-flow", "/statements", "Cash flow"),
  {
    name: "general_ledger",
    description: "Every ledger line of one account in a period, with running balance.",
    input_schema: { type: "object", properties: { accountId, periodId: period }, required: ["accountId", "periodId"] },
    page: "/statements",
    build: (i, c) => ({ method: "GET", path: `${base(c)}/statements/general-ledger`, query: { accountId: uuid(i, "accountId", true), periodId: uuid(i, "periodId", true) } }),
    describe: (i, ctx) => `General ledger of one account, ${ofPeriod(ctx, i)}`,
  },
  {
    name: "ledger_balances",
    description:
      "The cumulative balance of every ledger account and the main statement totals (total assets, liabilities, equity, income, expense, net profit, balance check) for a period, as the engine computes them. Account ids here are the ones what_if takes.",
    input_schema: { type: "object", properties: { periodId: period }, required: ["periodId"] },
    page: "/impact",
    build: (i, c) => ({ method: "GET", path: `${base(c)}/dependency-graph`, query: { periodId: uuid(i, "periodId", true) } }),
    describe: (i, ctx) => `Account balances and statement totals, ${ofPeriod(ctx, i)}`,
    shape: (data) => {
      const nodes = (data as { nodes?: Array<Record<string, unknown>> })?.nodes;
      if (!Array.isArray(nodes)) return data;
      const accounts: unknown[] = [];
      const totals: unknown[] = [];
      for (const n of nodes) {
        if (n.kind === "ledger") {
          const meta = (n.meta ?? {}) as Record<string, unknown>;
          accounts.push({ accountId: meta.account_id, code: meta.code, name: meta.name, type: meta.account_type, balance: n.value });
        } else {
          totals.push({ label: n.label, value: n.value, formula: n.formula });
        }
      }
      return { accounts, statement_totals: totals };
    },
  },
  {
    name: "what_if",
    description:
      "'Change one thing, see every impact': recalculates the statements if the given accounts had the given cumulative balances. It saves and posts nothing. Returns each changed figure with before, after and delta, as computed by the engine. Use ledger_balances first to get account ids and current balances.",
    input_schema: {
      type: "object",
      properties: {
        periodId: period,
        changes: {
          type: "array",
          description: "1 to 10 accounts and the balance each should have in the what-if.",
          items: {
            type: "object",
            properties: { accountId, newBalance: { type: "string", description: "The new cumulative balance as a plain decimal such as 20000.00 (no commas)." } },
            required: ["accountId", "newBalance"],
          },
        },
      },
      required: ["periodId", "changes"],
    },
    page: "/impact",
    build: (i, c) => {
      const raw = i.changes;
      if (!Array.isArray(raw) || raw.length === 0 || raw.length > 10) throw new ToolInputError("changes must list 1 to 10 accounts");
      const overrides: Record<string, string> = {};
      for (const item of raw) {
        const row = (item ?? {}) as Record<string, unknown>;
        const id = uuid(row, "accountId", true);
        const value = typeof row.newBalance === "number" ? String(row.newBalance) : row.newBalance;
        if (typeof value !== "string" || !AMOUNT.test(value.trim())) throw new ToolInputError("newBalance must be a plain decimal such as 20000.00");
        overrides[`acct:${id}:cum`] = value.trim();
      }
      return { method: "POST", path: `${base(c)}/dependency-graph/recompute`, body: { periodId: uuid(i, "periodId", true), overrides } };
    },
    describe: (i, ctx) => `What-if recalculation (nothing saved), ${ofPeriod(ctx, i)}`,
  },
  {
    name: "trace_account",
    description: "Where an account's balance comes from: its ledger lines and the source rows, vouchers or imports behind each one.",
    input_schema: { type: "object", properties: { accountId, periodId: period, scope: { type: "string", enum: ["period", "cumulative"] } }, required: ["accountId", "periodId"] },
    page: "/impact",
    build: (i, c) => {
      const query: Record<string, string> = { accountId: uuid(i, "accountId", true), periodId: uuid(i, "periodId", true) };
      const scope = oneOf(i, "scope", ["period", "cumulative"]);
      if (scope) query.scope = scope;
      return { method: "GET", path: `${base(c)}/dependency-graph/trace`, query };
    },
    describe: (i, ctx) => `Where one account's balance comes from, ${ofPeriod(ctx, i)}`,
  },
  periodTool("fixed_assets", "The fixed-asset roll-forward and depreciation schedule for a period.", "schedules/fixed-assets", "/schedules", "Fixed-asset schedule"),
  periodTool("fixed_assets_reconcile", "Whether the fixed-asset schedule agrees with the ledger for a period, and the differences.", "schedules/fixed-assets/reconcile", "/schedules", "Fixed-asset schedule against ledger"),
  {
    name: "exceptions_summary",
    description: "Counts of flagged exceptions (by status, priority and category) for the company, optionally for one period.",
    input_schema: { type: "object", properties: { periodId: period } },
    page: "/exceptions",
    build: (i, c) => {
      const p = uuid(i, "periodId", false);
      return { method: "GET", path: `${base(c)}/exceptions/summary`, query: opt("periodId", p) };
    },
    describe: (i, ctx) => `Exceptions summary${i.periodId ? `, ${ofPeriod(ctx, i)}` : ""}`,
  },
  {
    name: "list_exceptions",
    description: "Flagged exceptions (unusual or suspicious entries) with their status, priority and category. Newest first, up to 50.",
    input_schema: {
      type: "object",
      properties: {
        periodId: period,
        status: { type: "string", enum: [...FLAG_STATUSES] },
        category: { type: "string", enum: [...FLAG_CATEGORIES] },
        priority: { type: "string", enum: [...FLAG_PRIORITIES] },
        openOnly: { type: "boolean", description: "True to list only flags that still need attention (flagged, under review, awaiting evidence or awaiting correction)." },
        limit: { type: "integer", description: "1 to 50, default 25." },
      },
    },
    page: "/exceptions",
    build: (i, c) => {
      const query: Record<string, string> = {};
      const p = uuid(i, "periodId", false);
      if (p) query.periodId = p;
      const status = oneOf(i, "status", FLAG_STATUSES);
      if (status) query.status = status;
      const category = oneOf(i, "category", FLAG_CATEGORIES);
      if (category) query.category = category;
      const priority = oneOf(i, "priority", FLAG_PRIORITIES);
      if (priority) query.priority = priority;
      if (i.openOnly === true) query.openOnly = "true";
      query.limit = String(intIn(i, "limit", 1, 50) ?? 25);
      return { method: "GET", path: `${base(c)}/exceptions`, query };
    },
    describe: () => "Flagged exceptions",
  },
  {
    name: "get_exception",
    description: "One exception with its history, linked adjustments and the entries it is about.",
    input_schema: { type: "object", properties: { exceptionId: { type: "string", description: "Id from list_exceptions." } }, required: ["exceptionId"] },
    page: "/exceptions",
    build: (i, c) => ({ method: "GET", path: `${base(c)}/exceptions/${uuid(i, "exceptionId", true)}` }),
    describe: () => "One exception in detail",
  },
  periodTool("reconciliation", "The latest reconciliation run for a period: what matched, what did not, and why.", "reconciliation", "/reconciliation", "Latest reconciliation"),
  {
    name: "approvals_summary",
    description: "Counts of items waiting for approval, waiting for the current person, waiting on others, and decided.",
    input_schema: { type: "object", properties: { periodId: period } },
    page: "/approvals",
    build: (i, c) => {
      const p = uuid(i, "periodId", false);
      return { method: "GET", path: `${base(c)}/approvals/summary`, query: opt("periodId", p) };
    },
    describe: (i, ctx) => `Approvals summary${i.periodId ? `, ${ofPeriod(ctx, i)}` : ""}`,
  },
  {
    name: "approvals_inbox",
    description: "What is waiting for approval, oldest first, and whether the current person may decide each item (and if not, why not).",
    input_schema: {
      type: "object",
      properties: {
        periodId: period,
        scope: { type: "string", enum: ["all", "mine", "waiting"], description: "mine = the person can decide it now; waiting = the person made it." },
      },
    },
    page: "/approvals",
    build: (i, c) => {
      const query: Record<string, string> = {};
      const p = uuid(i, "periodId", false);
      if (p) query.periodId = p;
      const scope = oneOf(i, "scope", ["all", "mine", "waiting"]);
      if (scope) query.scope = scope;
      return { method: "GET", path: `${base(c)}/approvals/inbox`, query };
    },
    describe: () => "Approvals waiting",
  },
  {
    name: "list_scenarios",
    description: "What-if scenarios (changes being simulated, reviewed or posted), optionally filtered by status.",
    input_schema: { type: "object", properties: { status: { type: "string", enum: [...SCENARIO_STATUSES] } } },
    page: "/simulator",
    build: (i, c) => {
      const status = oneOf(i, "status", SCENARIO_STATUSES);
      return { method: "GET", path: `${base(c)}/scenarios`, query: opt("status", status) };
    },
    describe: () => "Scenarios",
  },
  {
    name: "scenario_impact",
    description: "A scenario's impact report: current against scenario against the difference for every affected figure.",
    input_schema: { type: "object", properties: { scenarioId: { type: "string", description: "Id from list_scenarios." } }, required: ["scenarioId"] },
    page: "/impact",
    build: (i, c) => ({ method: "GET", path: `${base(c)}/scenarios/${uuid(i, "scenarioId", true)}/impact` }),
    describe: () => "Scenario impact report",
  },
  {
    name: "list_adjustments",
    description: "Proposed, approved and posted adjusting entries, optionally filtered by status.",
    input_schema: { type: "object", properties: { status: { type: "string", enum: [...ADJUSTMENT_STATUSES] } } },
    page: "/adjustments",
    build: (i, c) => {
      const status = oneOf(i, "status", ADJUSTMENT_STATUSES);
      return { method: "GET", path: `${base(c)}/adjustments`, query: opt("status", status) };
    },
    describe: () => "Adjusting entries",
  },
  {
    name: "audit_summary",
    description: "Counts of recorded audit-trail events (who did what), optionally for one period. Only people with audit access can see this.",
    input_schema: { type: "object", properties: { periodId: period } },
    page: "/audit",
    build: (i, c) => {
      const p = uuid(i, "periodId", false);
      return { method: "GET", path: `${base(c)}/audit-events/summary`, query: opt("periodId", p) };
    },
    describe: () => "Audit trail summary",
  },
];

const BY_NAME = new Map(TOOLS.map((t) => [t.name, t]));
export const toolByName = (name: string): ToolDef | undefined => BY_NAME.get(name);

/** What is sent to the model: name, description and argument schema only. */
export const TOOL_SPECS = TOOLS.map((t) => ({ name: t.name, description: t.description, input_schema: t.input_schema }));