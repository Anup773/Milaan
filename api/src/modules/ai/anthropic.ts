/**
 * The one place that talks to the model: Anthropic's Messages API with tool use, over plain fetch (no SDK needed).
 * Configuration comes from the environment, read at call time so the API starts fine without it:
 *   ANTHROPIC_API_KEY   required to use the assistant
 *   ANTHROPIC_MODEL     default "claude-sonnet-5-5"
 *   AI_API_URL          default "https://api.anthropic.com" (tests point it at a stand-in server)
 *   AI_MAX_TOKENS       default 2000 (the longest single reply)
 */

export type ContentBlock =
  | { type: "text"; text: string }
  | { type: "tool_use"; id: string; name: string; input: Record<string, unknown> }
  | { type: "tool_result"; tool_use_id: string; content: string; is_error?: boolean };

export interface ModelMessage {
  role: "user" | "assistant";
  content: string | ContentBlock[];
}

export interface ModelRequest {
  system: string;
  messages: ModelMessage[];
  tools: Array<{ name: string; description: string; input_schema: unknown }>;
}

export interface ModelResponse {
  content: ContentBlock[];
  stop_reason: string;
  usage?: { input_tokens?: number; output_tokens?: number };
}

export type ModelCall = (req: ModelRequest) => Promise<ModelResponse>;

/** An error that is safe to show to the person, with the HTTP status the API should answer with. */
export class AiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "AiError";
    this.status = status;
  }
}

export interface AiConfig {
  apiKey: string;
  model: string;
  baseUrl: string;
  maxTokens: number;
}

export function readConfig(env: NodeJS.ProcessEnv = process.env): AiConfig | null {
  const apiKey = env.ANTHROPIC_API_KEY?.trim();
  if (!apiKey) return null;
  const maxTokens = Number(env.AI_MAX_TOKENS);
  return {
    apiKey,
    model: env.ANTHROPIC_MODEL?.trim() || "claude-sonnet-5-5",
    baseUrl: (env.AI_API_URL?.trim() || "https://api.anthropic.com").replace(/\/+$/, ""),
    maxTokens: Number.isInteger(maxTokens) && maxTokens >= 200 && maxTokens <= 8000 ? maxTokens : 2000,
  };
}

const REQUEST_TIMEOUT_MS = 90_000;

export function createModelCaller(config: AiConfig, fetchImpl: typeof fetch = fetch): ModelCall {
  return async (req) => {
    let res: Response;
    try {
      res = await fetchImpl(`${config.baseUrl}/v1/messages`, {
        method: "POST",
        headers: { "content-type": "application/json", "x-api-key": config.apiKey, "anthropic-version": "2023-06-01" },
        body: JSON.stringify({ model: config.model, max_tokens: config.maxTokens, system: req.system, messages: req.messages, tools: req.tools }),
        signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
      });
    } catch (err) {
      const timedOut = (err as { name?: string })?.name === "TimeoutError";
      throw new AiError(504, timedOut ? "The AI service took too long to answer. Try again." : "Could not reach the AI service. Check the server's internet access and try again.");
    }
    if (!res.ok) {
      let detail = "";
      try {
        const data = (await res.json()) as { error?: { message?: unknown } };
        if (typeof data?.error?.message === "string") detail = data.error.message.slice(0, 200);
      } catch {
        /* no JSON body */
      }
      if (res.status === 401 || res.status === 403) throw new AiError(502, "The AI service did not accept the API key set on the server. Ask the administrator to check ANTHROPIC_API_KEY.");
      if (res.status === 429) throw new AiError(429, "The AI service is busy or its usage limit is reached. Try again in a minute.");
      if (res.status === 529 || res.status >= 500) throw new AiError(503, "The AI service is temporarily unavailable. Try again in a minute.");
      throw new AiError(502, `The AI service refused the request${detail ? `: ${detail}` : ""}.`);
    }
    let data: ModelResponse;
    try {
      data = (await res.json()) as ModelResponse;
    } catch {
      throw new AiError(502, "The AI service sent a reply that could not be read.");
    }
    if (!data || !Array.isArray(data.content) || typeof data.stop_reason !== "string") throw new AiError(502, "The AI service sent a reply that could not be read.");
    return data;
  };
}