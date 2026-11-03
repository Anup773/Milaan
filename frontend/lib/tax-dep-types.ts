// Shapes returned by GET /companies/:id/tax-depreciation and the write routes beside it. Amounts travel as text.
import type { Calendar, FiscalYearInfo } from "./policy-types";

export type Scheme = "NP" | "IN" | "US";
export type MovementKind = "OPENING" | "ADDITION" | "DISPOSAL";

export interface TaxColumn {
  key: string;
  label: string;
  /** True for amounts, which are formatted with the company's grouping. */
  money: boolean;
}

/** One row of the schedule (a pool, a block or a recovery class). The keys that exist depend on the country; `columns` says which to show. */
export interface TaxRow {
  pool: string;
  name?: string;
  rate?: string;
  rate_source?: string;
  notes?: string[];
  [key: string]: string | string[] | undefined;
}

export interface TaxMovement {
  id: string;
  pool: string;
  kind: MovementKind;
  event_date: string;
  amount: string;
  description: string;
  details: Record<string, string | boolean>;
  fiscal_year: string;
}

export interface TaxRate {
  id: string;
  pool: string;
  rate: string;
  effective_from: string;
  note: string;
}

export interface RatePreset {
  name: string;
  rates: Record<string, string>;
  note: string;
}

export interface TaxSchedule {
  scheme: Scheme;
  scheme_name: string;
  fiscal_year: FiscalYearInfo;
  pools: TaxRow[];
  columns: TaxColumn[];
  totals: Record<string, string>;
  /** The United States only: one line per asset. */
  lines: Array<Record<string, string>>;
  line_columns: TaxColumn[];
  notes: string[];
  warnings: string[];
  pool_choices: Array<{ code: string; name: string }>;
  rate_presets: RatePreset[];
  standard_rates: Array<{ pool: string; rate: string; effective_from: string; note: string }>;
  company_rates: TaxRate[];
  movements: TaxMovement[];
  years_with_data: string[];
  can_edit: boolean;
  calendar: Calendar;
}
