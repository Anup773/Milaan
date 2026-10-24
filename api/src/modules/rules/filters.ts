/**
 * Reads the query string of GET /rules. Only the shape is checked here (short, plain text, not something that could
 * be mistaken for a command-line option); whether a family or status is a real one is the engine's call, and it
 * answers 400 with the list of valid values.
 */

export interface RuleFilters {
  family: string | null;
  jurisdiction: string | null;
  framework: string | null;
  status: string | null;
}

export class FilterError extends Error {}

const TEXT = /^[A-Za-z0-9][A-Za-z0-9 ._&/-]{0,39}$/;
const RULE_SET_ID = /^[a-z0-9][a-z0-9-]{0,39}$/;

function one(query: Record<string, unknown>, key: string): string | null {
  const raw = query[key];
  if (raw === undefined || raw === null) return null;
  if (typeof raw !== "string") throw new FilterError(`${key} must be given once`);
  const value = raw.trim();
  if (value === "") return null;
  if (!TEXT.test(value)) throw new FilterError(`${key} is not valid`);
  return value;
}

export function parseFilters(query: Record<string, unknown>): RuleFilters {
  return {
    family: one(query, "family"),
    jurisdiction: one(query, "jurisdiction"),
    framework: one(query, "framework"),
    status: one(query, "status"),
  };
}

/** The arguments for the engine's `catalog` command: every filter in order, "-" for one that is not set. */
export function catalogArgs(f: RuleFilters): string[] {
  return ["catalog", f.family ?? "-", f.jurisdiction ?? "-", f.framework ?? "-", f.status ?? "-"];
}

export function parseRuleSetId(value: unknown): string {
  if (typeof value !== "string" || !RULE_SET_ID.test(value)) throw new FilterError("that is not a valid rule set id");
  return value;
}