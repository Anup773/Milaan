import { test } from "node:test";
import assert from "node:assert/strict";
import { AiError, createModelCaller, readConfig } from "./anthropic.js";

const config = { apiKey: "sk-test", model: "m1", baseUrl: "https://ai.example", maxTokens: 1000 };
const request = { system: "S", messages: [{ role: "user" as const, content: "hi" }], tools: [{ name: "t", description: "d", input_schema: { type: "object" } }] };
const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

test("no key means the assistant is off; defaults fill the rest", () => {
  assert.equal(readConfig({}), null);
  assert.equal(readConfig({ ANTHROPIC_API_KEY: "  " }), null);
  assert.deepEqual(readConfig({ ANTHROPIC_API_KEY: "k" }), { apiKey: "k", model: "claude-sonnet-5-5", baseUrl: "https://api.anthropic.com", maxTokens: 2000 });
  assert.deepEqual(readConfig({ ANTHROPIC_API_KEY: "k", ANTHROPIC_MODEL: "x", AI_API_URL: "http://h:1/", AI_MAX_TOKENS: "500" }), { apiKey: "k", model: "x", baseUrl: "http://h:1", maxTokens: 500 });
  assert.equal(readConfig({ ANTHROPIC_API_KEY: "k", AI_MAX_TOKENS: "99999" })!.maxTokens, 2000);
});

test("the request is a Messages API call with the key, version, model, tools and no key in the body", async () => {
  let seen: { url: string; init: RequestInit } | null = null;
  const call = createModelCaller(config, (async (url: unknown, init?: RequestInit) => {
    seen = { url: String(url), init: init! };
    return json(200, { content: [{ type: "text", text: "ok" }], stop_reason: "end_turn", usage: { input_tokens: 1, output_tokens: 2 } });
  }) as typeof fetch);
  const out = await call(request);
  assert.equal(out.stop_reason, "end_turn");
  assert.equal(seen!.url, "https://ai.example/v1/messages");
  const headers = seen!.init.headers as Record<string, string>;
  assert.equal(headers["x-api-key"], "sk-test");
  assert.equal(headers["anthropic-version"], "2023-06-01");
  const body = JSON.parse(String(seen!.init.body));
  assert.deepEqual(Object.keys(body).sort(), ["max_tokens", "messages", "model", "system", "tools"]);
  assert.equal(body.model, "m1");
  assert.equal(body.max_tokens, 1000);
  assert.ok(!JSON.stringify(body).includes("sk-test"));
});

async function failure(status: number, body: unknown = { error: { message: "detail" } }): Promise<AiError> {
  const call = createModelCaller(config, (async () => json(status, body)) as typeof fetch);
  return (await call(request).then(
    () => assert.fail("should have thrown"),
    (e) => e,
  )) as AiError;
}

test("service errors become messages a person can act on, never echoing the key", async () => {
  const unauthorized = await failure(401);
  assert.equal(unauthorized.status, 502);
  assert.match(unauthorized.message, /ANTHROPIC_API_KEY/);
  assert.ok(!unauthorized.message.includes("sk-test"));
  assert.equal((await failure(429)).status, 429);
  assert.equal((await failure(529)).status, 503);
  assert.equal((await failure(500)).status, 503);
  const refused = await failure(400, { error: { message: "prompt is too long" } });
  assert.equal(refused.status, 502);
  assert.match(refused.message, /prompt is too long/);
});

test("a network failure, a timeout and garbage replies are all reported plainly", async () => {
  const offline = createModelCaller(config, (async () => { throw new TypeError("fetch failed"); }) as typeof fetch);
  await assert.rejects(offline(request), (e: AiError) => e.status === 504 && /Could not reach/.test(e.message));
  const slow = createModelCaller(config, (async () => { throw Object.assign(new Error("t"), { name: "TimeoutError" }); }) as typeof fetch);
  await assert.rejects(slow(request), (e: AiError) => e.status === 504 && /too long/.test(e.message));
  const garbage = createModelCaller(config, (async () => new Response("<html>", { status: 200 })) as typeof fetch);
  await assert.rejects(garbage(request), (e: AiError) => e.status === 502);
  const wrongShape = createModelCaller(config, (async () => json(200, { hello: 1 })) as typeof fetch);
  await assert.rejects(wrongShape(request), (e: AiError) => e.status === 502);
});