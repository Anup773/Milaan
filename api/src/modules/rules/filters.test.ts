import test from "node:test";
import assert from "node:assert/strict";
import { FilterError, catalogArgs, parseFilters, parseRuleSetId } from "./filters.js";

test("no query means no filters, and every position is skipped with '-'", () => {
  const f = parseFilters({});
  assert.deepEqual(f, { family: null, jurisdiction: null, framework: null, status: null });
  assert.deepEqual(catalogArgs(f), ["catalog", "-", "-", "-", "-"]);
});

test("filters are trimmed and passed in the engine's order", () => {
  const f = parseFilters({ family: " tax ", jurisdiction: "IN", framework: "Ind AS", status: "ACTIVE" });
  assert.deepEqual(catalogArgs(f), ["catalog", "tax", "IN", "Ind AS", "ACTIVE"]);
});

test("blank values count as not set", () => {
  assert.deepEqual(parseFilters({ family: "", jurisdiction: "   " }), { family: null, jurisdiction: null, framework: null, status: null });
});

test("a repeated or non-text value is refused", () => {
  assert.throws(() => parseFilters({ family: ["tax", "audit"] }), FilterError);
  assert.throws(() => parseFilters({ framework: { a: 1 } }), FilterError);
});

test("values that could be read as options, or are long or odd, are refused", () => {
  for (const bad of ["-x", "--help", "a;b", "a`b", "$(x)", "x".repeat(41), "a\nb"]) {
    assert.throws(() => parseFilters({ family: bad }), FilterError, bad);
  }
});

test("framework names with spaces, dots and slashes are accepted", () => {
  for (const ok of ["FRS 102", "Income tax", "ISO/IEC 27001", "A&B", "SA"]) {
    assert.equal(parseFilters({ framework: ok }).framework, ok);
  }
});

test("rule set ids are lower-case words and dashes", () => {
  assert.equal(parseRuleSetId("ind-as"), "ind-as");
  assert.equal(parseRuleSetId("frs-102"), "frs-102");
  for (const bad of ["", "Ind-AS", "-x", "a b", "../x", "x".repeat(41), 5, undefined]) {
    assert.throws(() => parseRuleSetId(bad), FilterError, String(bad));
  }
});