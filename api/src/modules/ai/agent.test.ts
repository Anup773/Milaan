import { test } from "node:test";
import assert from "node:assert/strict";
import type { ContentBlock, ModelCall, ModelRequest, ModelResponse } from "./anthropic.js";
import { MAX_CALLS_PER_ROUND, MAX_ROUNDS, runAgent, type ToolOutcome, type ToolRunner } from "./agent.js";

const text = (t: string): ContentBlock => ({ type: "text", text: t });
const use = (id: string, name: string, input: Record<string, unknown> = {}): ContentBlock => ({ type: "tool_use", id, name, input });
const reply = (content: ContentBlock[], stop_reason = "end_turn"): ModelResponse => ({ content, stop_reason, usage: { input_tokens: 100, output_tokens: 20 } });

/** A model that plays a fixed script and remembers what it was sent. */
function scripted(steps: ModelResponse[]): { call: ModelCall; seen: ModelRequest[] } {
  const seen: ModelRequest[] = [];
  let i = 0;
  return {
    seen,
    call: async (req) => {
      seen.push(JSON.parse(JSON.stringify(req)) as ModelRequest);
      const step = steps[Math.min(i, steps.length - 1)];
      i += 1;
      return step;
    },
  };
}

const ok = (body: unknown, label = "Profit and loss"): ToolOutcome => ({ ok: true, text: JSON.stringify(body), label, page: "/statements" });
const history = [{ role: "user" as const, text: "What is net profit?" }];

test("the model looks something up, gets the data, and answers from it", async () => {
  const model = scripted([reply([text("Let me check."), use("t1", "profit_loss", { periodId: "p" })], "tool_use"), reply([text("Net profit is -402700.10.")])]);
  const calls: string[] = [];
  const runTool: ToolRunner = async (name, input) => {
    calls.push(`${name}:${JSON.stringify(input)}`);
    return ok({ net_profit: "-402700.10" });
  };
  const r = await runAgent({ system: "S", history, callModel: model.call, runTool });
  assert.equal(r.answer, "Net profit is -402700.10.");
  assert.deepEqual(calls, ['profit_loss:{"periodId":"p"}']);
  assert.deepEqual(r.lookedAt, [{ tool: "profit_loss", label: "Profit and loss", ok: true, page: "/statements" }]);
  assert.deepEqual(r.unverified, []);
  assert.deepEqual(r.usage, { rounds: 2, toolCalls: 1, inputTokens: 200, outputTokens: 40 });
  // the second request carries the assistant's tool call and the tool's result back, in the form the API requires
  const second = model.seen[1].messages;
  assert.equal(second.length, 3);
  assert.equal(second[1].role, "assistant");
  assert.deepEqual(second[2], { role: "user", content: [{ type: "tool_result", tool_use_id: "t1", content: '{"net_profit":"-402700.10"}' }] });
  assert.equal(model.seen[0].system, "S");
  assert.ok(model.seen[0].tools.length > 10);
});

test("a figure the model worked out itself is flagged for the person", async () => {
  const model = scripted([reply([use("t1", "profit_loss")], "tool_use"), reply([text("Income is 14,300.00 and expense 417,000.10, so the loss is 402,700.10. Total 431,300.10.")])]);
  const r = await runAgent({ system: "S", history, callModel: model.call, runTool: async () => ok({ income: "14300.00", expense: "417000.10", net: "-402700.10" }) });
  assert.deepEqual(r.unverified, ["431,300.10"]);
});

test("a figure the person typed is not flagged", async () => {
  const model = scripted([reply([text("With 20,000.00 as asked, nothing was saved.")])]);
  const r = await runAgent({ system: "S", history: [{ role: "user", text: "What if receivables were 20000?" }], callModel: model.call, runTool: async () => ok({}) });
  assert.deepEqual(r.unverified, []);
});

test("the same lookup asked twice is run once, in one round or across rounds", async () => {
  const model = scripted([
    reply([use("a", "profit_loss", { periodId: "p" }), use("b", "profit_loss", { periodId: "p" })], "tool_use"),
    reply([use("c", "profit_loss", { periodId: "p" })], "tool_use"),
    reply([text("Done.")]),
  ]);
  let runs = 0;
  const r = await runAgent({ system: "S", history, callModel: model.call, runTool: async () => (runs++, ok({})) });
  assert.equal(runs, 1);
  assert.equal(r.lookedAt.length, 1);
  assert.equal(r.usage.toolCalls, 1);
  const results = model.seen[2].messages.at(-1)!.content as ContentBlock[];
  assert.equal(results.length, 1);
});

test("a failed lookup reaches the model as an error it can explain, and shows as failed", async () => {
  const model = scripted([reply([use("t1", "audit_summary")], "tool_use"), reply([text("You do not have access to the audit trail.")])]);
  const r = await runAgent({
    system: "S",
    history,
    callModel: model.call,
    runTool: async () => ({ ok: false, text: '{"error":"role not allowed"}', label: "Audit trail summary", page: "/audit" }),
  });
  const result = (model.seen[1].messages.at(-1)!.content as ContentBlock[])[0];
  assert.deepEqual(result, { type: "tool_result", tool_use_id: "t1", content: '{"error":"role not allowed"}', is_error: true });
  assert.equal(r.lookedAt[0].ok, false);
});

test("a tool runner that throws does not break the question", async () => {
  const model = scripted([reply([use("t1", "profit_loss")], "tool_use"), reply([text("I could not load it.")])]);
  const r = await runAgent({ system: "S", history, callModel: model.call, runTool: async () => { throw new Error("boom"); } });
  assert.equal(r.answer, "I could not load it.");
  assert.equal(r.lookedAt[0].ok, false);
});

test("too many lookups in one round: the extra ones are refused, not run", async () => {
  const many = Array.from({ length: MAX_CALLS_PER_ROUND + 2 }, (_, i) => use(`t${i}`, "profit_loss", { n: i }));
  const model = scripted([reply(many, "tool_use"), reply([text("Done.")])]);
  let runs = 0;
  const r = await runAgent({ system: "S", history, callModel: model.call, runTool: async () => (runs++, ok({})) });
  assert.equal(runs, MAX_CALLS_PER_ROUND);
  const results = model.seen[1].messages.at(-1)!.content as Array<{ is_error?: boolean }>;
  assert.equal(results.length, MAX_CALLS_PER_ROUND + 2);
  assert.equal(results.filter((x) => x.is_error).length, 2);
  assert.equal(r.answer, "Done.");
});

test("a model that never stops asking is cut off after a fixed number of rounds", async () => {
  let n = 0;
  const call: ModelCall = async () => reply([use(`t${n}`, "profit_loss", { n: n++ })], "tool_use");
  const r = await runAgent({ system: "S", history, callModel: call, runTool: async () => ok({}) });
  assert.equal(r.stopped, "limit");
  assert.equal(r.usage.rounds, MAX_ROUNDS);
  assert.match(r.answer, /reached my limit/);
  assert.deepEqual(r.unverified, []);
});

test("an answer cut short by the length limit is marked, and an empty answer is replaced", async () => {
  const cut = await runAgent({ system: "S", history, callModel: scripted([reply([text("Net profit is")], "max_tokens")]).call, runTool: async () => ok({}) });
  assert.equal(cut.stopped, "length");
  const empty = await runAgent({ system: "S", history, callModel: scripted([reply([])]).call, runTool: async () => ok({}) });
  assert.match(empty.answer, /could not produce an answer/);
});

test("earlier turns of the conversation are sent as plain messages", async () => {
  const model = scripted([reply([text("Yes.")])]);
  await runAgent({
    system: "S",
    history: [
      { role: "user", text: "q1" },
      { role: "assistant", text: "a1" },
      { role: "user", text: "q2" },
    ],
    callModel: model.call,
    runTool: async () => ok({}),
  });
  assert.deepEqual(model.seen[0].messages, [
    { role: "user", content: "q1" },
    { role: "assistant", content: "a1" },
    { role: "user", content: "q2" },
  ]);
});