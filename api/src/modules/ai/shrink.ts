/**
 * Keeps a tool result small enough to hand to the model. Long lists are cut to their first items and say how many
 * were left out, so the result is still valid JSON and the model knows it is looking at part of the data.
 * Nothing is rewritten or rounded: values that stay are exactly as the engine returned them.
 */

export const MAX_RESULT_CHARS = 24_000;

function cut(value: unknown, maxItems: number, maxText: number): unknown {
  if (Array.isArray(value)) {
    const kept = value.slice(0, maxItems).map((v) => cut(v, maxItems, maxText));
    if (value.length > maxItems) kept.push(`... ${value.length - maxItems} more items not shown`);
    return kept;
  }
  if (value !== null && typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) out[k] = cut(v, maxItems, maxText);
    return out;
  }
  if (typeof value === "string" && value.length > maxText) return `${value.slice(0, maxText)}... (${value.length - maxText} more characters)`;
  return value;
}

export interface Shrunk {
  text: string;
  truncated: boolean;
}

export function shrinkForModel(value: unknown, maxChars: number = MAX_RESULT_CHARS): Shrunk {
  const full = JSON.stringify(value) ?? "null";
  if (full.length <= maxChars) return { text: full, truncated: false };
  for (const maxItems of [200, 100, 50, 25, 12, 6, 3, 1]) {
    const text = JSON.stringify(cut(value, maxItems, 400));
    if (text.length <= maxChars) return { text, truncated: true };
  }
  // Even three items per list is too much (very wide objects): fall back to a marked prefix.
  return { text: `${full.slice(0, maxChars)} ... (result cut: ${full.length - maxChars} more characters)`, truncated: true };
}