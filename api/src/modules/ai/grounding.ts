/**
 * "Verify everything" for the assistant: every figure in an answer should be one the assistant actually looked up.
 *
 * The model is told to quote figures exactly as the tools returned them and never to add, subtract or round. This
 * check does not trust that: it pulls every figure out of the answer and looks for it among the figures in the
 * tool results, the tool inputs and the person's own messages. Anything that is not there (a sum the model worked
 * out, a rounded number, a made-up one) is returned so the screen can say so.
 *
 * Deliberately NOT checked, because they are not amounts: dates, ids, years, and whole numbers below 100 (counts
 * such as "3 exceptions", list numbers, percentages like 10%).
 */

const UUID = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi;
const ISO_DATE = /\b\d{4}-\d{2}-\d{2}\b/g;
const SLASH_DATE = /\b\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}\b/g;
const NODE_ID = /\b(?:acct|bs|pl):[\w:.-]*/gi;
// Digits (with comma groups of any size, so 1,65,000.00 and 165,000.00 both match), optional decimals.
const NUMBER = /(?<!\w)\d[\d,]*(?:\.\d+)?/g;

function stripNoise(text: string): string {
  return text.replace(UUID, " ").replace(NODE_ID, " ").replace(ISO_DATE, " ").replace(SLASH_DATE, " ");
}

/** "1,65,000.50" -> "165000.5"; "16638.40" -> "16638.4"; "10,000" -> "10000". Sign is ignored (a loss is quoted as a loss). */
export function normalizeNumber(raw: string): string {
  let s = raw.replace(/,/g, "");
  if (s.includes(".")) {
    s = s.replace(/0+$/, "").replace(/\.$/, "");
  }
  s = s.replace(/^0+(?=\d)/, "");
  return s;
}

function isChecked(normalized: string, raw: string): boolean {
  if (normalized.includes(".")) return true; // anything with decimals is an amount
  if (normalized.length <= 2) return false; // small counts, list numbers, percentages
  if (!raw.includes(",") && /^(19|20)\d{2}$/.test(normalized)) return false; // a year
  return true;
}

/** Every figure in a piece of text, normalised, in order of appearance (duplicates kept). */
export function figuresIn(text: string): Array<{ raw: string; normalized: string }> {
  const out: Array<{ raw: string; normalized: string }> = [];
  for (const match of stripNoise(text).matchAll(NUMBER)) {
    const raw = match[0].replace(/,+$/, ""); // a trailing comma belongs to the sentence
    out.push({ raw, normalized: normalizeNumber(raw) });
  }
  return out;
}

/** Everything the assistant is allowed to quote: the numbers in these texts, normalised (small ones included). */
export function knownFigures(texts: string[]): Set<string> {
  const known = new Set<string>();
  for (const text of texts) {
    for (const f of figuresIn(text)) known.add(f.normalized);
  }
  return known;
}

/**
 * The figures in `answer` that are not among `known`. Each is reported once, as written in the answer.
 * A figure written as 16638.4 matches 16,638.40 in the data (same value), and a negative in the data matches the
 * same amount written without its sign.
 */
export function unverifiedFigures(answer: string, known: Set<string>): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const f of figuresIn(answer)) {
    if (!isChecked(f.normalized, f.raw)) continue;
    if (known.has(f.normalized) || seen.has(f.normalized)) continue;
    seen.add(f.normalized);
    out.push(f.raw);
  }
  return out;
}
