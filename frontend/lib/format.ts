// Display helpers. Money arrives from the API as exact decimal STRINGS ("120000.00"); it is formatted by
// working on the string, never by turning it into a JavaScript float, so no figure is ever rounded or drifts.

const DECIMAL = /^-?\d+(\.\d+)?$/;

/** True if `value` is a plain decimal such as "120000", "-45.5" or "0.00". */
export function isDecimal(value: unknown): value is string {
  return typeof value === "string" && DECIMAL.test(value.trim());
}

/** Indian digit grouping: 1234567 -> "12,34,567". */
function groupIndian(digits: string): string {
  if (digits.length <= 3) return digits;
  const last3 = digits.slice(-3);
  let rest = digits.slice(0, -3);
  const parts: string[] = [];
  while (rest.length > 2) {
    parts.unshift(rest.slice(-2));
    rest = rest.slice(0, -2);
  }
  if (rest) parts.unshift(rest);
  return `${parts.join(",")},${last3}`;
}

/**
 * "-120000.5" -> "-1,20,000.50". Always two decimals. Anything that is not a decimal is returned as "-".
 * Negative amounts keep a leading minus (a ledger shows credits as negative balances; hiding that would mislead).
 */
export function formatMoney(value: string | null | undefined): string {
  if (value === null || value === undefined || !isDecimal(value)) return "-";
  const text = value.trim();
  const negative = text.startsWith("-");
  const unsigned = negative ? text.slice(1) : text;
  const [whole, fraction = ""] = unsigned.split(".");
  // Round half away from zero on the third decimal, still on strings.
  let cents = (fraction + "00").slice(0, 2);
  let wholeDigits = whole.replace(/^0+(?=\d)/, "");
  if (fraction.length > 2 && Number(fraction[2]) >= 5) {
    const bumped = (BigInt(wholeDigits + cents) + 1n).toString().padStart(3, "0");
    wholeDigits = bumped.slice(0, -2);
    cents = bumped.slice(-2);
  }
  const isZero = /^0*$/.test(wholeDigits) && cents === "00";
  return `${negative && !isZero ? "-" : ""}${groupIndian(wholeDigits || "0")}.${cents}`;
}

/** True when two decimal strings are the same amount to the cent ("10.0" equals "10.00"). */
export function sameAmount(a: string | null | undefined, b: string | null | undefined): boolean {
  const left = formatMoney(a);
  return left !== "-" && left === formatMoney(b);
}

/** Signed variant for deltas: "+9,000.00", "-9,000.00", "0.00". */
export function formatDelta(value: string | null | undefined): string {
  const text = formatMoney(value);
  if (text === "-" || text === "0.00") return text;
  return text.startsWith("-") ? text : `+${text}`;
}

/** The sign of a decimal string: -1, 0 or 1 (0 for anything that is not a decimal). */
export function signOf(value: string | null | undefined): -1 | 0 | 1 {
  if (!isDecimal(value)) return 0;
  const text = value.trim();
  if (/^-?0*(\.0*)?$/.test(text)) return 0;
  return text.startsWith("-") ? -1 : 1;
}

/** "20.00" -> "20.0%". null -> "-". */
export function formatPct(value: string | null | undefined): string {
  if (!isDecimal(value)) return "-";
  const n = Number(value);
  return `${n > 0 ? "+" : ""}${n.toFixed(1)}%`;
}

/**
 * Validates an amount typed by a person: optional minus, digits, optional 1-2 decimals ("54000", "-12.5").
 * Returns the cleaned string, or null when it is not a valid amount. Commas and spaces are tolerated.
 */
export function parseAmountInput(raw: string): string | null {
  const cleaned = raw.replace(/[,\s]/g, "");
  return /^-?\d+(\.\d{1,2})?$/.test(cleaned) ? cleaned : null;
}

/** "2025-04-01" -> "01 Apr 2025". Calendar dates are never passed through the Date constructor (no timezone shifts). */
export function formatDate(value: string | null | undefined): string {
  if (!value) return "-";
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  if (!match) return value;
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const month = months[Number(match[2]) - 1];
  if (!month) return value;
  return `${match[3]} ${month} ${match[1]}`;
}

/** A moment from the API ("2026-10-14 04:35:01.943802+00:00") shown in the viewer's own time zone. */
export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "-";
  const iso = value.replace(" ", "T");
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** "SIMULATED" -> "Simulated"; "EVIDENCE_REQUESTED" -> "Evidence requested". */
export function humanise(value: string | null | undefined): string {
  if (!value) return "-";
  const text = value.replace(/[_-]+/g, " ").toLowerCase();
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** First 8 characters of an id, for places where the full uuid would be noise. */
export function shortId(id: string | null | undefined): string {
  return id ? id.slice(0, 8) : "-";
}
