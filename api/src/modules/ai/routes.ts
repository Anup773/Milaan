import { Router, type Request } from "express";
import { authenticate } from "../auth/middleware.js";
import { assertCompanyInFirm } from "../companies/access.js";
import { respondError, type StatusError } from "../../lib/http.js";
import { withTenant } from "../../db/client.js";
import { AiError, createModelCaller, readConfig } from "./anthropic.js";
import { runAgent, type ToolOutcome, type ToolRunner } from "./agent.js";
import { buildSystemPrompt, type PromptPeriod } from "./prompt.js";
import { RateLimiter } from "./rateLimit.js";
import { shrinkForModel } from "./shrink.js";
import { ToolInputError, toolByName } from "./tools.js";

export const aiRouter = Router();

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const MAX_MESSAGES = 20;
const MAX_MESSAGE_CHARS = 4000;
const MAX_TOTAL_CHARS = 60_000;
const TOOL_TIMEOUT_MS = 40_000;
// 20 questions in 10 minutes per person.
const limiter = new RateLimiter(20, 10 * 60 * 1000);

function bad(message: string): StatusError {
  const err = new Error(message) as StatusError;
  err.status = 400;
  return err;
}

/** Says whether the assistant is switched on (an API key is set on the server). The screen asks this before showing the chat. */
aiRouter.get("/status", authenticate, (_req, res) => {
  const config = readConfig();
  res.json({ enabled: config !== null, model: config?.model ?? null });
});

interface Question {
  companyId: string;
  periodId: string | null;
  history: Array<{ role: "user" | "assistant"; text: string }>;
}

function readQuestion(req: Request): Question {
  const body = (req.body ?? {}) as Record<string, unknown>;
  if (typeof body.companyId !== "string" || !UUID.test(body.companyId)) throw bad("companyId is required");
  let periodId: string | null = null;
  if (body.periodId !== undefined && body.periodId !== null && body.periodId !== "") {
    if (typeof body.periodId !== "string" || !UUID.test(body.periodId)) throw bad("periodId is not valid");
    periodId = body.periodId;
  }
  const raw = body.messages;
  if (!Array.isArray(raw) || raw.length === 0) throw bad("messages must list the conversation so far, ending with the question");
  if (raw.length > MAX_MESSAGES) throw bad(`the conversation is too long (limit ${MAX_MESSAGES} messages). Start a new one`);
  const history: Question["history"] = [];
  let total = 0;
  raw.forEach((item, index) => {
    const m = (item ?? {}) as Record<string, unknown>;
    const expected = index % 2 === 0 ? "user" : "assistant";
    if (m.role !== expected) throw bad("messages must alternate between the person and the assistant, starting with the person");
    let text = typeof m.text === "string" ? m.text.trim() : "";
    if (!text) throw bad("a message is empty");
    if (text.length > MAX_MESSAGE_CHARS) {
      // The assistant's own earlier answers can be long; keep their start. A question that is too long is the person's to shorten.
      if (expected === "user") throw bad(`a message is too long (limit ${MAX_MESSAGE_CHARS} characters)`);
      text = `${text.slice(0, MAX_MESSAGE_CHARS)}...`;
    }
    total += text.length;
    history.push({ role: expected, text });
  });
  if (history[history.length - 1].role !== "user") throw bad("the last message must be the person's question");
  if (total > MAX_TOTAL_CHARS) throw bad("the conversation is too long. Start a new one");
  return { companyId: body.companyId, periodId, history };
}

/** Runs one read-only lookup against this same API as the person (their token, so their role and company limits apply). */
function makeToolRunner(req: Request, companyId: string, periodLabel: (id: string) => string): ToolRunner {
  const origin = `http://127.0.0.1:${req.socket.localPort}`;
  const authorization = req.headers.authorization ?? "";
  return async (name, input): Promise<ToolOutcome> => {
    const tool = toolByName(name);
    if (!tool) return { ok: false, text: JSON.stringify({ error: `there is no tool called ${name}` }), label: name, page: "/dashboard" };
    const label = (() => {
      try {
        return tool.describe(input, { periodLabel });
      } catch {
        return tool.name;
      }
    })();
    const fail = (message: string): ToolOutcome => ({ ok: false, text: JSON.stringify({ error: message }), label, page: tool.page });
    let spec;
    try {
      spec = tool.build(input, companyId);
    } catch (err) {
      return fail(err instanceof ToolInputError ? err.message : "the request was not valid");
    }
    const url = new URL(origin + spec.path);
    for (const [k, v] of Object.entries(spec.query ?? {})) url.searchParams.set(k, v);
    try {
      const res = await fetch(url, {
        method: spec.method,
        headers: { authorization, ...(spec.body !== undefined ? { "content-type": "application/json" } : {}) },
        body: spec.body !== undefined ? JSON.stringify(spec.body) : undefined,
        signal: AbortSignal.timeout(TOOL_TIMEOUT_MS),
      });
      let data: unknown = null;
      try {
        data = await res.json();
      } catch {
        /* an empty or non-JSON body */
      }
      if (!res.ok) {
        const message = typeof (data as { error?: unknown })?.error === "string" ? (data as { error: string }).error : `the lookup failed (${res.status})`;
        return fail(message);
      }
      const shaped = tool.shape ? tool.shape(data) : data;
      const { text, truncated } = shrinkForModel(shaped);
      return { ok: true, text: truncated ? `${text}\n(This result was too long; only the start of each long list is shown.)` : text, label, page: tool.page };
    } catch {
      return fail("the lookup timed out or could not be completed");
    }
  };
}

aiRouter.post("/ask", authenticate, async (req, res) => {
  try {
    const config = readConfig();
    if (!config) {
      res.status(503).json({ error: "The assistant is not switched on. The administrator needs to set ANTHROPIC_API_KEY on the API server." });
      return;
    }
    const auth = req.auth!;
    const q = readQuestion(req);
    await assertCompanyInFirm(auth.firmId, q.companyId);

    const allowed = limiter.take(auth.userId);
    if (!allowed.ok) {
      res.setHeader("retry-after", String(allowed.retryAfterSeconds));
      res.status(429).json({ error: `You have asked a lot of questions in a short time. Try again in ${allowed.retryAfterSeconds} seconds.` });
      return;
    }

    const context = await withTenant({ firmId: auth.firmId, companyId: q.companyId }, async (client) => {
      const company = await client.query(`SELECT name FROM companies WHERE id = $1`, [q.companyId]);
      const periods = await client.query(
        `SELECT id, label, period_start, period_end, lock_status FROM accounting_periods WHERE company_id = $1 ORDER BY period_start`,
        [q.companyId],
      );
      return { name: String(company.rows[0]?.name ?? "this company"), periods: periods.rows as PromptPeriod[] };
    });
    const labels = new Map(context.periods.map((p) => [p.id.toLowerCase(), p.label]));
    const system = buildSystemPrompt({
      companyName: context.name,
      periods: context.periods,
      focusPeriodId: q.periodId && labels.has(q.periodId.toLowerCase()) ? q.periodId : null,
      today: new Date().toISOString().slice(0, 10),
      personRole: auth.role,
    });

    const result = await runAgent({
      system,
      history: q.history,
      callModel: createModelCaller(config),
      runTool: makeToolRunner(req, q.companyId, (id) => labels.get(id.toLowerCase()) ?? "a period"),
    });
    res.json({
      answer: result.answer,
      looked_at: result.lookedAt,
      unverified_figures: result.unverified,
      stopped: result.stopped,
      usage: result.usage,
    });
  } catch (err) {
    if (err instanceof AiError) {
      res.status(err.status).json({ error: err.message });
      return;
    }
    respondError(res, err, "the assistant failed");
  }
});