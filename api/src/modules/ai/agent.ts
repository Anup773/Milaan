/**
 * The question-answering loop. The model asks for tools, the API runs them (read-only, as the person), the results
 * go back, and the loop ends when the model writes its answer. Bounded: a fixed number of rounds and tool calls.
 *
 * Nothing here knows about HTTP, the database or Anthropic: the model and the tool runner are passed in, so the
 * whole loop is tested with scripted fakes.
 */
import type { ContentBlock, ModelCall, ModelMessage } from "./anthropic.js";
import { TOOL_SPECS } from "./tools.js";
import { knownFigures, unverifiedFigures } from "./grounding.js";

export const MAX_ROUNDS = 8;
export const MAX_TOOL_CALLS = 14;
export const MAX_CALLS_PER_ROUND = 6;

export interface ToolOutcome {
  ok: boolean;
  /** Exactly what the model sees. */
  text: string;
  /** For the person: what was looked at, and the screen that shows it. */
  label: string;
  page: string;
}

export type ToolRunner = (name: string, input: Record<string, unknown>) => Promise<ToolOutcome>;

export interface LookedAt {
  tool: string;
  label: string;
  ok: boolean;
  page: string;
}

export interface AgentResult {
  answer: string;
  lookedAt: LookedAt[];
  unverified: string[];
  stopped: "limit" | "length" | null;
  usage: { rounds: number; toolCalls: number; inputTokens: number; outputTokens: number };
}

export interface AgentInput {
  system: string;
  history: Array<{ role: "user" | "assistant"; text: string }>;
  callModel: ModelCall;
  runTool: ToolRunner;
}

const textOf = (blocks: ContentBlock[]): string =>
  blocks
    .filter((b): b is Extract<ContentBlock, { type: "text" }> => b.type === "text" && typeof b.text === "string")
    .map((b) => b.text.trim())
    .filter(Boolean)
    .join("\n\n");

export async function runAgent(input: AgentInput): Promise<AgentResult> {
  const messages: ModelMessage[] = input.history.map((m) => ({ role: m.role, content: m.text }));
  const lookedAt: LookedAt[] = [];
  const cache = new Map<string, Promise<ToolOutcome>>();
  const shown = new Set<string>();
  const seenTexts: string[] = input.history.filter((m) => m.role === "user").map((m) => m.text);
  const usage = { rounds: 0, toolCalls: 0, inputTokens: 0, outputTokens: 0 };

  let answer = "";
  let stopped: AgentResult["stopped"] = null;
  let finished = false;

  for (let round = 0; round < MAX_ROUNDS && !finished; round++) {
    const response = await input.callModel({ system: input.system, messages, tools: TOOL_SPECS });
    usage.rounds += 1;
    usage.inputTokens += response.usage?.input_tokens ?? 0;
    usage.outputTokens += response.usage?.output_tokens ?? 0;

    const toolUses = response.content.filter((b): b is Extract<ContentBlock, { type: "tool_use" }> => b.type === "tool_use");
    if (response.stop_reason !== "tool_use" || toolUses.length === 0) {
      answer = textOf(response.content);
      if (response.stop_reason === "max_tokens") stopped = "length";
      finished = true;
      break;
    }

    messages.push({ role: "assistant", content: response.content });
    const room = Math.max(0, Math.min(MAX_CALLS_PER_ROUND, MAX_TOOL_CALLS - usage.toolCalls));
    const settled = await Promise.all(
      toolUses.map(async (use, index) => {
        const args = use.input && typeof use.input === "object" ? use.input : {};
        if (index >= room) return { use, args, key: "", outcome: null };
        const key = `${use.name}:${JSON.stringify(args)}`;
        let pending = cache.get(key);
        if (!pending) {
          pending = input.runTool(use.name, args).catch(
            (): ToolOutcome => ({ ok: false, text: JSON.stringify({ error: "that lookup failed" }), label: use.name, page: "/dashboard" }),
          );
          cache.set(key, pending);
        }
        return { use, args, key, outcome: await pending };
      }),
    );
    const results: ContentBlock[] = [];
    for (const { use, args, key, outcome } of settled) {
      if (!outcome) {
        results.push({ type: "tool_result", tool_use_id: use.id, is_error: true, content: JSON.stringify({ error: "too many lookups in one question; answer with what you already have" }) });
        continue;
      }
      if (!shown.has(key)) {
        shown.add(key);
        lookedAt.push({ tool: use.name, label: outcome.label, ok: outcome.ok, page: outcome.page });
        seenTexts.push(JSON.stringify(args), outcome.text);
        usage.toolCalls += 1;
      }
      results.push({ type: "tool_result", tool_use_id: use.id, content: outcome.text, ...(outcome.ok ? {} : { is_error: true }) });
    }
    messages.push({ role: "user", content: results });
  }

  if (!finished) {
    stopped = "limit";
    answer = "I reached my limit on lookups for one question before I could finish. Ask a narrower question (one statement, one account or one period) and I will answer it.";
  }
  if (!answer) answer = "I could not produce an answer to that. Try asking it another way.";

  const unverified = stopped === "limit" ? [] : unverifiedFigures(answer, knownFigures(seenTexts));
  return { answer, lookedAt, unverified, stopped, usage };
}