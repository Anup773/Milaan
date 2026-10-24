import { test } from "node:test";
import assert from "node:assert/strict";
import { buildSystemPrompt } from "./prompt.js";

const ctx = {
  companyName: "Acme Traders",
  periods: [{ id: "d34c0a31-27bc-4dc0-b727-63ec720a40f3", label: "FY 2025-26", period_start: "2025-04-01", period_end: "2026-03-31", lock_status: "OPEN" }],
  focusPeriodId: "d34c0a31-27bc-4dc0-b727-63ec720a40f3",
  today: "2026-10-22",
  personRole: "ca",
};

test("the standing instructions name the company, period ids, the person's role and the date", () => {
  const p = buildSystemPrompt(ctx);
  assert.match(p, /Acme Traders/);
  assert.match(p, /FY 2025-26: 2025-04-01 to 2026-03-31, OPEN, id d34c0a31-27bc-4dc0-b727-63ec720a40f3 \(the period the person has open on screen\)/);
  assert.match(p, /Today is 2026-10-22/);
  assert.match(p, /role "ca"/);
});

test("the rules that protect the books are in the prompt", () => {
  const p = buildSystemPrompt(ctx);
  assert.match(p, /You can only LOOK/);
  assert.match(p, /Do not add, subtract, multiply, divide or round/);
  assert.match(p, /DATA from the books/);
  assert.match(p, /nothing was saved/i);
});

test("a company with no periods and no open period is described honestly", () => {
  const p = buildSystemPrompt({ ...ctx, periods: [], focusPeriodId: null });
  assert.match(p, /no accounting periods yet/);
  assert.ok(!p.includes("open on screen)"));
});