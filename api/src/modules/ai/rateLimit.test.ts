import { test } from "node:test";
import assert from "node:assert/strict";
import { RateLimiter } from "./rateLimit.js";

test("allows up to the limit, then says when to retry, per person", () => {
  const limiter = new RateLimiter(3, 60_000);
  assert.equal(limiter.take("a", 0).ok, true);
  assert.equal(limiter.take("a", 1000).ok, true);
  assert.equal(limiter.take("a", 2000).ok, true);
  const blocked = limiter.take("a", 3000);
  assert.equal(blocked.ok, false);
  assert.equal(blocked.retryAfterSeconds, 57);
  assert.equal(limiter.take("b", 3000).ok, true);
});

test("attempts expire with the window", () => {
  const limiter = new RateLimiter(1, 10_000);
  assert.equal(limiter.take("a", 0).ok, true);
  assert.equal(limiter.take("a", 5000).ok, false);
  assert.equal(limiter.take("a", 10_000).ok, true);
});

test("a refused attempt does not extend the wait", () => {
  const limiter = new RateLimiter(1, 10_000);
  limiter.take("a", 0);
  limiter.take("a", 9000);
  assert.equal(limiter.take("a", 10_000).ok, true);
});