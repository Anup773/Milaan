// Turns rows pasted from a spreadsheet into entries for the tax depreciation schedule. Pure functions, no network.
//
// Columns, in order (a header row is skipped if the first cell says "kind"):
//   kind, pool, date, amount, description, then the extras for the country:
//   Nepal: life_years (pool E), deferred / accumulated for an opening balance of pool E, dissolves_pool (yes) for a disposal
//   India: block_ceases (yes) for a disposal
//   United States: asset_ref, section_179, bonus_percent  (a disposal: asset_ref)
// Dates are written the way the company writes them: BS (2082-04-01) for a BS company, otherwise year-month-day.
import { bsToAd } from "./bs-calendar";
import type { Scheme } from "./tax-dep-types";

export interface EntryBody {
  kind: string;
  pool: string;
  event_date: string;
  amount: string;
  description: string;
  details: Record<string, string | boolean>;
}

const KINDS = ["OPENING", "ADDITION", "DISPOSAL"];
const YES = /^(y|yes|true|1|x)$/i;

/** A date typed or pasted by the company, as AD YYYY-MM-DD; null when it is not a real date. */
export function toAdDate(text: string, calendar: "AD" | "BS"): string | null {
  const t = text.trim().replace(/[/.]/g, "-");
  const m = /^(\d{4})-(\d{1,2})-(\d{1,2})$/.exec(t);
  if (!m) return null;
  const [y, mo, d] = [Number(m[1]), Number(m[2]), Number(m[3])];
  try {
    if (calendar === "BS") return bsToAd(y, mo, d);
  } catch {
    return null;
  }
  const iso = `${m[1]}-${String(mo).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
  const check = new Date(Date.UTC(y, mo - 1, d));
  return check.getUTCFullYear() === y && check.getUTCMonth() === mo - 1 && check.getUTCDate() === d ? iso : null;
}

function split(line: string): string[] {
  const cells = line.includes("\t") ? line.split("\t") : line.split(",");
  return cells.map((c) => c.trim().replace(/^"(.*)"$/, "$1"));
}

export function parsePaste(text: string, scheme: Scheme, calendar: "AD" | "BS"): { rows: EntryBody[]; errors: string[] } {
  const rows: EntryBody[] = [];
  const errors: string[] = [];
  const lines = text.split(/\r?\n/).filter((l) => l.trim() !== "");
  lines.forEach((line, i) => {
    const n = i + 1;
    const c = split(line);
    if (i === 0 && /^kind$/i.test(c[0] ?? "")) return;
    const kind = (c[0] ?? "").toUpperCase();
    if (!KINDS.includes(kind)) return void errors.push(`Row ${n}: the first column must be OPENING, ADDITION or DISPOSAL.`);
    const date = toAdDate(c[2] ?? "", calendar);
    if (!date) return void errors.push(`Row ${n}: "${c[2] ?? ""}" is not a ${calendar === "BS" ? "BS date like 2082-04-01" : "date like 2025-04-01"}.`);
    const amount = (c[3] ?? "").replace(/[,\s]/g, "");
    if (!/^\d+(\.\d{1,2})?$/.test(amount)) return void errors.push(`Row ${n}: "${c[3] ?? ""}" is not an amount.`);
    const details: Record<string, string | boolean> = {};
    const extra = c.slice(5);
    const put = (key: string, value: string | undefined) => {
      if (value !== undefined && value !== "") details[key] = value.replace(/,/g, "");
    };
    if (scheme === "NP") {
      if (kind === "DISPOSAL") {
        if (YES.test(extra[0] ?? "")) details.dissolves_pool = true;
      } else {
        put("life_years", extra[0]);
        if (kind === "OPENING") {
          put("deferred", extra[1]);
          put("accumulated", extra[2]);
        }
      }
    } else if (scheme === "IN") {
      if (kind === "DISPOSAL" && YES.test(extra[0] ?? "")) details.block_ceases = true;
    } else if (kind === "ADDITION") {
      put("asset_ref", extra[0]);
      put("section_179", extra[1]);
      put("bonus_percent", extra[2]);
    } else {
      put("asset_ref", extra[0]);
    }
    rows.push({ kind, pool: c[1] ?? "", event_date: date, amount, description: c[4] ?? "", details });
  });
  if (rows.length === 0 && errors.length === 0) errors.push("There is nothing to add: paste at least one row.");
  return { rows, errors };
}