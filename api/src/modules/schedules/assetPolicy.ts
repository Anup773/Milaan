/**
 * What the company's accounting policy (Phase 22) says about adding a fixed asset: an asset that costs less than the
 * capitalisation threshold is not capitalised (it is expensed instead), and an asset added without a useful life
 * takes the policy's default. Kept free of the database so it can be tested on its own; the route reads the policy
 * row and hands it in.
 */

export interface AssetPolicy {
  /** numeric(18,2) as the database returns it, e.g. "5000.00" */
  capitalization_threshold: string;
  default_useful_life_months: number | null;
}

export class AssetPolicyError extends Error {}

/** "5000.00" -> 500000. Works on the text, so no binary-float error can creep in. */
export function toCents(amount: string): number {
  const m = /^(\d{1,15})(?:\.(\d{1,2}))?$/.exec(amount.trim());
  if (!m) throw new AssetPolicyError(`not an amount: ${amount}`);
  return Number(m[1]) * 100 + Number((m[2] ?? "").padEnd(2, "0") || "0");
}

export function costInCents(cost: number): number {
  return Math.round(cost * 100);
}

export function applyAssetPolicy(
  input: { cost: number; usefulLifeMonths: number | undefined | null },
  policy: AssetPolicy | null,
): { usefulLifeMonths: number } {
  if (policy) {
    const threshold = toCents(policy.capitalization_threshold);
    if (threshold > 0 && costInCents(input.cost) < threshold) {
      throw new AssetPolicyError(
        `this company's accounting policy only capitalises assets that cost at least ${policy.capitalization_threshold}. ` +
          "Record a smaller purchase as an expense instead",
      );
    }
  }
  if (input.usefulLifeMonths !== undefined && input.usefulLifeMonths !== null) return { usefulLifeMonths: input.usefulLifeMonths };
  if (policy && policy.default_useful_life_months !== null && policy.default_useful_life_months !== undefined) {
    return { usefulLifeMonths: policy.default_useful_life_months };
  }
  throw new AssetPolicyError("usefulLifeMonths is required (the company's accounting policy has no default useful life)");
}