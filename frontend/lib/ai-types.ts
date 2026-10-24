// Shapes returned by the /ai API routes.

export interface AiStatus {
  enabled: boolean;
  model: string | null;
}

export interface AiLookup {
  tool: string;
  label: string;
  ok: boolean;
  page: string; // the screen that shows the same thing, e.g. "/statements"
}

export interface AiAnswer {
  answer: string;
  looked_at: AiLookup[];
  unverified_figures: string[];
  stopped: "limit" | "length" | null;
  usage: { rounds: number; toolCalls: number; inputTokens: number; outputTokens: number };
}