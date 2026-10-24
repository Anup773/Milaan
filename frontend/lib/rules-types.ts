// Shapes returned by GET /rules.

export type RuleFamily = "accounting" | "auditing" | "tax" | "compliance";
export type RuleSetStatus = "ACTIVE" | "CATALOG_ONLY";
export type Coverage = "FULL" | "PARTIAL" | "NONE";

export interface RuleCheckRef {
  kind: "reconciliation" | "exception" | "feature";
  id: string;
  title: string | null;
}

export interface RuleItem {
  id: string;
  reference: string;
  title: string;
  description: string;
  coverage: Coverage;
  note: string;
  checks: RuleCheckRef[];
}

export interface RuleSet {
  id: string;
  family: RuleFamily;
  title: string;
  framework: string;
  jurisdiction: string; // a country code, or INTL for every country
  authority: string;
  status: RuleSetStatus;
  description: string;
  coverage: Record<Coverage, number>;
  items: RuleItem[];
}

export interface RulesCatalog {
  notice: string;
  families: Array<{ id: RuleFamily; title: string; description: string; rule_sets: number }>;
  rule_sets: RuleSet[];
  summary: { rule_sets: number; active: number; catalog_only: number; items: number; items_with_checks: number };
  filters: { jurisdictions: string[]; frameworks: string[] };
}
