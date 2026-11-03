import test from "node:test";
import assert from "node:assert/strict";
import { AssetPolicyError, applyAssetPolicy, costInCents, toCents } from "./assetPolicy.js";

const policy = (threshold: string, life: number | null) => ({ capitalization_threshold: threshold, default_useful_life_months: life });

test("amounts are read from text in cents", () => {
  assert.equal(toCents("5000.00"), 500000);
  assert.equal(toCents("0.5"), 50);
  assert.equal(toCents("0"), 0);
  assert.equal(toCents("999999999999999.99"), 99999999999999999);
  assert.throws(() => toCents("abc"), AssetPolicyError);
  assert.throws(() => toCents("-1"), AssetPolicyError);
});

test("a cost in rupees and paise becomes whole cents without float drift", () => {
  assert.equal(costInCents(0.29), 29);
  assert.equal(costInCents(19.99), 1999);
  assert.equal(costInCents(1.15), 115); // 1.15 * 100 is 114.99999999999999 in binary floating point
  assert.equal(costInCents(4999.99), 499999);
  assert.equal(costInCents(1005), 100500);
});

test("without a policy nothing changes: a life must be given", () => {
  assert.deepEqual(applyAssetPolicy({ cost: 100, usefulLifeMonths: 60 }, null), { usefulLifeMonths: 60 });
  assert.throws(() => applyAssetPolicy({ cost: 100, usefulLifeMonths: undefined }, null), /usefulLifeMonths is required/);
});

test("an asset below the threshold is refused, one at or above it is accepted", () => {
  const p = policy("5000.00", null);
  assert.throws(() => applyAssetPolicy({ cost: 4999.99, usefulLifeMonths: 12 }, p), /at least 5000\.00/);
  assert.deepEqual(applyAssetPolicy({ cost: 5000, usefulLifeMonths: 12 }, p), { usefulLifeMonths: 12 });
  assert.deepEqual(applyAssetPolicy({ cost: 5000.01, usefulLifeMonths: 12 }, p), { usefulLifeMonths: 12 });
});

test("a threshold of zero means no threshold", () => {
  assert.deepEqual(applyAssetPolicy({ cost: 0.01, usefulLifeMonths: 12 }, policy("0.00", null)), { usefulLifeMonths: 12 });
});

test("the policy's default useful life fills in a missing one, but never overrides a given one", () => {
  const p = policy("0.00", 60);
  assert.deepEqual(applyAssetPolicy({ cost: 100, usefulLifeMonths: undefined }, p), { usefulLifeMonths: 60 });
  assert.deepEqual(applyAssetPolicy({ cost: 100, usefulLifeMonths: null }, p), { usefulLifeMonths: 60 });
  assert.deepEqual(applyAssetPolicy({ cost: 100, usefulLifeMonths: 24 }, p), { usefulLifeMonths: 24 });
});

test("a policy with no default life still needs one to be given", () => {
  assert.throws(() => applyAssetPolicy({ cost: 100, usefulLifeMonths: undefined }, policy("0.00", null)), /no default useful life/);
});

test("the threshold is checked even when the life comes from the default", () => {
  assert.throws(() => applyAssetPolicy({ cost: 10, usefulLifeMonths: undefined }, policy("100.00", 60)), /at least 100\.00/);
});