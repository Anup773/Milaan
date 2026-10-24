import { test } from "node:test";
import assert from "node:assert/strict";
import { figuresIn, knownFigures, normalizeNumber, unverifiedFigures } from "./grounding.js";

test("figures are compared by value, not by how they are written", () => {
  assert.equal(normalizeNumber("16,638.40"), "16638.4");
  assert.equal(normalizeNumber("16638.4"), "16638.4");
  assert.equal(normalizeNumber("1,65,000.00"), "165000");
  assert.equal(normalizeNumber("165,000"), "165000");
  assert.equal(normalizeNumber("0.50"), "0.5");
  assert.equal(normalizeNumber("007"), "7");
});

test("a figure that was looked up is verified, whatever the grouping or decimals", () => {
  const known = knownFigures(['{"total":"16638.40","tax":"1,980.05"}']);
  assert.deepEqual(unverifiedFigures("Receivables are 16,638.40 and input tax is 1980.05.", known), []);
  assert.deepEqual(unverifiedFigures("Receivables are Rs.16,638.4", known), []);
});

test("a figure the assistant worked out or invented is reported once, as written", () => {
  const known = knownFigures(['{"a":"1000.00","b":"250.00"}']);
  assert.deepEqual(unverifiedFigures("Together that is 1,250.00. Again 1250.00. Also 999.99.", known), ["1,250.00", "999.99"]);
});

test("a loss quoted without its sign still matches the data", () => {
  const known = knownFigures(['{"net_profit":"-402700.10"}']);
  assert.deepEqual(unverifiedFigures("There is a loss of 402,700.10.", known), []);
});

test("figures the person typed count as known", () => {
  const known = knownFigures(["What if receivables were 20000?"]);
  assert.deepEqual(unverifiedFigures("With 20,000 receivables the total changes.", known), []);
});

test("counts, percentages, years, dates, ids and codes in the data are not treated as amounts", () => {
  const known = knownFigures(['{"id":"18077a2c-ef57-4616-835e-eab7211f1891","code":"7101"}']);
  const answer = "There are 3 open flags (12%), in FY 2025-26, dated 2026-03-31 and 31/03/2026, account 7101, id 18077a2c-ef57-4616-835e-eab7211f1891, node acct:18077a2c-ef57-4616-835e-eab7211f1891:cum.";
  assert.deepEqual(unverifiedFigures(answer, known), []);
});

test("a year written with a comma group is still an amount, and so is any figure with decimals", () => {
  assert.deepEqual(unverifiedFigures("It is 2,025 and 5.5.", new Set()), ["2,025", "5.5"]);
});

test("a number at the end of a sentence loses the sentence's punctuation, not its value", () => {
  const known = knownFigures(["total 5000"]);
  assert.deepEqual(unverifiedFigures("The total is 5,000, and 6,000.", known), ["6,000"]);
  assert.deepEqual(figuresIn("pay 1,200.").map((f) => f.normalized), ["1200"]);
});

test("a figure that only appears inside a bigger number does not verify it", () => {
  const known = knownFigures(['{"v":"123456.00"}']);
  assert.deepEqual(unverifiedFigures("The figure is 3456.00", known), ["3456.00"]);
});