import { test } from "node:test";
import assert from "node:assert/strict";
import { TOOLS, TOOL_SPECS, ToolInputError, toolByName } from "./tools.js";

const COMPANY = "22222222-2222-2222-2222-222222222222";
const PERIOD = "d34c0a31-27bc-4dc0-b727-63ec720a40f3";
const ACCOUNT = "18077a2c-ef57-4616-835e-eab7211f1891";
const ctx = { periodLabel: (id: string) => (id === PERIOD ? "FY 2025-26" : "a period") };

test("tool names are unique and every schema is well formed", () => {
  assert.equal(new Set(TOOLS.map((t) => t.name)).size, TOOLS.length);
  for (const t of TOOLS) {
    assert.equal(t.input_schema.type, "object", t.name);
    for (const key of t.input_schema.required ?? []) assert.ok(key in t.input_schema.properties, `${t.name}: required ${key} is not a property`);
    assert.ok(t.description.length > 20, t.name);
    assert.match(t.page, /^\/[a-z-]+$/);
  }
  assert.deepEqual(Object.keys(TOOL_SPECS[0]).sort(), ["description", "input_schema", "name"]);
});

test("the assistant can only look: the single POST is the what-if calculation", () => {
  const sample: Record<string, unknown> = { periodId: PERIOD, accountId: ACCOUNT, exceptionId: ACCOUNT, scenarioId: ACCOUNT, changes: [{ accountId: ACCOUNT, newBalance: "1.00" }] };
  const methods = new Map<string, string>();
  for (const t of TOOLS) {
    const req = t.build(sample, COMPANY);
    methods.set(t.name, req.method);
    assert.ok(req.path.startsWith(`/companies/${COMPANY}/`), `${t.name} must stay inside the company: ${req.path}`);
    assert.ok(!/post|approve|finali|decide|claim|resolve|import|simulate|submit/i.test(req.path.replace("recompute", "")), `${t.name} path looks like an action: ${req.path}`);
  }
  assert.deepEqual([...methods].filter(([, m]) => m !== "GET"), [["what_if", "POST"]]);
});

test("ids must be ids: anything else is refused before any request is made", () => {
  assert.throws(() => toolByName("profit_loss")!.build({ periodId: "../../etc/passwd" }, COMPANY), ToolInputError);
  assert.throws(() => toolByName("profit_loss")!.build({}, COMPANY), /periodId is required/);
  assert.throws(() => toolByName("general_ledger")!.build({ periodId: PERIOD, accountId: "1; drop table" }, COMPANY), ToolInputError);
  assert.throws(() => toolByName("get_exception")!.build({ exceptionId: 5 }, COMPANY), ToolInputError);
});

test("a period tool builds exactly the route the screens use", () => {
  assert.deepEqual(toolByName("profit_loss")!.build({ periodId: PERIOD.toUpperCase() }, COMPANY), {
    method: "GET",
    path: `/companies/${COMPANY}/statements/profit-loss`,
    query: { periodId: PERIOD },
  });
  assert.equal(toolByName("fixed_assets_reconcile")!.build({ periodId: PERIOD }, COMPANY).path, `/companies/${COMPANY}/schedules/fixed-assets/reconcile`);
  assert.equal(toolByName("ledger_balances")!.build({ periodId: PERIOD }, COMPANY).path, `/companies/${COMPANY}/dependency-graph`);
});

test("filters are limited to the engine's own values", () => {
  const list = toolByName("list_exceptions")!;
  assert.deepEqual(list.build({ status: "FLAGGED", priority: "HIGH", category: "DUPLICATE_INVOICE", openOnly: true, limit: 10 }, COMPANY).query, {
    status: "FLAGGED",
    category: "DUPLICATE_INVOICE",
    priority: "HIGH",
    openOnly: "true",
    limit: "10",
  });
  assert.equal(list.build({}, COMPANY).query?.limit, "25");
  assert.throws(() => list.build({ status: "OPEN" }, COMPANY), /status must be one of/);
  assert.throws(() => list.build({ limit: 500 }, COMPANY), /limit must be/);
  assert.throws(() => toolByName("list_scenarios")!.build({ status: "whatever" }, COMPANY), ToolInputError);
  assert.deepEqual(toolByName("approvals_inbox")!.build({ scope: "mine" }, COMPANY).query, { scope: "mine" });
});

test("what_if turns account balances into the engine's override keys and nothing else", () => {
  const req = toolByName("what_if")!.build({ periodId: PERIOD, changes: [{ accountId: ACCOUNT, newBalance: "20000.00" }, { accountId: ACCOUNT.toUpperCase(), newBalance: 5 }] }, COMPANY);
  assert.equal(req.method, "POST");
  assert.equal(req.path, `/companies/${COMPANY}/dependency-graph/recompute`);
  assert.deepEqual(req.body, { periodId: PERIOD, overrides: { [`acct:${ACCOUNT}:cum`]: "5" } });
  const one = toolByName("what_if")!.build({ periodId: PERIOD, changes: [{ accountId: ACCOUNT, newBalance: "-20000.5" }] }, COMPANY);
  assert.deepEqual((one.body as { overrides: object }).overrides, { [`acct:${ACCOUNT}:cum`]: "-20000.5" });
});

test("what_if refuses bad input", () => {
  const t = toolByName("what_if")!;
  assert.throws(() => t.build({ periodId: PERIOD, changes: [] }, COMPANY), /1 to 10/);
  assert.throws(() => t.build({ periodId: PERIOD, changes: Array.from({ length: 11 }, () => ({ accountId: ACCOUNT, newBalance: "1" })) }, COMPANY), /1 to 10/);
  assert.throws(() => t.build({ periodId: PERIOD, changes: [{ accountId: ACCOUNT, newBalance: "1,000" }] }, COMPANY), /plain decimal/);
  assert.throws(() => t.build({ periodId: PERIOD, changes: [{ accountId: ACCOUNT, newBalance: "1e9" }] }, COMPANY), /plain decimal/);
  assert.throws(() => t.build({ periodId: PERIOD, changes: [{ accountId: "x", newBalance: "1" }] }, COMPANY), ToolInputError);
  assert.throws(() => t.build({ periodId: PERIOD }, COMPANY), /1 to 10/);
});

test("results are re-arranged, never recalculated", () => {
  const graph = {
    nodes: [
      { id: `acct:${ACCOUNT}:cum`, label: "7101 Trade Receivables (cumulative)", kind: "ledger", is_leaf: true, formula: null, value: "16638.40", meta: { account_id: ACCOUNT, code: "7101", name: "Trade Receivables", account_type: "Asset" } },
      { id: "pl:net_profit", label: "Net profit (FY 2025-26)", kind: "statement", is_leaf: false, formula: "difference", value: "-402700.10", meta: {} },
    ],
    edges: [{ from: "a", to: "b" }],
  };
  assert.deepEqual(toolByName("ledger_balances")!.shape!(graph), {
    accounts: [{ accountId: ACCOUNT, code: "7101", name: "Trade Receivables", type: "Asset", balance: "16638.40" }],
    statement_totals: [{ label: "Net profit (FY 2025-26)", value: "-402700.10", formula: "difference" }],
  });
  assert.deepEqual(toolByName("list_accounts")!.shape!({ accounts: [{ id: ACCOUNT, code: "7101", name: "X", account_type: "Asset", parent_account_id: null }] }), {
    accounts: [{ id: ACCOUNT, code: "7101", name: "X", type: "Asset" }],
  });
  assert.equal(toolByName("ledger_balances")!.shape!("odd"), "odd");
});

test("each lookup is described for the person in plain words", () => {
  assert.equal(toolByName("profit_loss")!.describe({ periodId: PERIOD }, ctx), "Profit and loss, FY 2025-26");
  assert.equal(toolByName("exceptions_summary")!.describe({}, ctx), "Exceptions summary");
});
