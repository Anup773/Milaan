import { test } from "node:test";
import assert from "node:assert/strict";
import { shrinkForModel } from "./shrink.js";

test("a small result is passed through untouched", () => {
  const out = shrinkForModel({ a: "1.50", rows: [1, 2, 3] });
  assert.equal(out.truncated, false);
  assert.deepEqual(JSON.parse(out.text), { a: "1.50", rows: [1, 2, 3] });
});

test("long lists are cut but stay valid JSON, say how much is missing, and keep exact values", () => {
  const rows = Array.from({ length: 5000 }, (_, i) => ({ n: i, amount: `${i}.10`, note: "x".repeat(20) }));
  const out = shrinkForModel({ total: "12345.67", rows }, 5000);
  assert.equal(out.truncated, true);
  assert.ok(out.text.length <= 5000);
  const parsed = JSON.parse(out.text) as { total: string; rows: unknown[] };
  assert.equal(parsed.total, "12345.67");
  assert.deepEqual(parsed.rows[0], { n: 0, amount: "0.10", note: "x".repeat(20) });
  assert.match(String(parsed.rows[parsed.rows.length - 1]), /more items not shown/);
});

test("very long text is shortened and says so", () => {
  const out = shrinkForModel({ memo: "y".repeat(100_000) }, 3000);
  assert.equal(out.truncated, true);
  assert.ok(out.text.length <= 3000);
  assert.match(out.text, /more characters/);
});

test("an impossible budget still returns something marked as cut", () => {
  const wide = Object.fromEntries(Array.from({ length: 3000 }, (_, i) => [`k${i}`, "v".repeat(30)]));
  const out = shrinkForModel(wide, 2000);
  assert.equal(out.truncated, true);
  assert.match(out.text, /result cut/);
});