// Shapes returned by GET and PUT /companies/:id/policy. Amounts travel as text ("5000.00") so no precision is lost.

export type Calendar = "AD" | "BS";
export type DateOrder = "DMY" | "MDY";
export type NumberGrouping = "INDIAN" | "WESTERN";
export type StatementRounding = "EXACT" | "WHOLE";

export interface PolicyValues {
  accounting_framework: string;
  jurisdiction: string;
  currency: string;
  calendar: Calendar;
  date_order: DateOrder;
  number_grouping: NumberGrouping;
  fiscal_year_start_month: number;
  tax_regime: string;
  depreciation_method: string;
  depreciation_start: string;
  default_useful_life_months: number | null;
  capitalization_threshold: string;
  inventory_valuation_method: string;
  statement_rounding: StatementRounding;
  review_min_amount: string;
  review_large_amount: string;
}

export type PolicyField = keyof PolicyValues;

export interface SavedPolicy extends PolicyValues {
  change_reason: string | null;
  updated_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface Option<V = string> {
  value: V;
  label: string;
}

export interface PolicyRuleSet {
  id: string;
  title: string;
  family: string;
  framework: string;
  jurisdiction: string;
  status: "ACTIVE" | "CATALOG_ONLY";
}

/** One line of a country's honest guide: what Milaan does for that country today. */
export interface GuideLine {
  topic: string;
  status: "built" | "partial" | "not_built";
  text: string;
}

/** The titles a country uses for the statements (the US says "Income Statement", India "Statement of Profit and Loss"). */
export interface StatementTitles {
  balance_sheet: string;
  profit_and_loss: string;
  cash_flow: string;
  changes_in_equity: string;
  trial_balance: string;
  profit_label: string;
  equity_label: string;
}

/** What "I am a company in <country>" sets up. `suggested` is the policy values to fill in. */
export interface CountryProfile {
  code: string;
  name: string;
  support: "full" | "basic";
  currency: string;
  calendar: Calendar;
  calendar_choices: Calendar[];
  date_order: DateOrder;
  number_grouping: NumberGrouping;
  fiscal_year_start_month: number;
  frameworks: string[];
  tax_regime: string;
  tax_regime_choices: string[];
  inventory_methods: string[];
  statement_rounding: StatementRounding;
  statements: StatementTitles;
  tax_depreciation_scheme: string | null;
  fiscal_year_note: string;
  guide: GuideLine[];
  suggested: Pick<
    PolicyValues,
    | "accounting_framework"
    | "jurisdiction"
    | "currency"
    | "calendar"
    | "date_order"
    | "number_grouping"
    | "fiscal_year_start_month"
    | "tax_regime"
    | "inventory_valuation_method"
    | "statement_rounding"
  >;
}

export interface PolicyView {
  policy: SavedPolicy | null;
  configured: boolean;
  /** Only the settings that have a built-in default (the company's identity has none). */
  defaults: Pick<
    PolicyValues,
    "depreciation_method" | "depreciation_start" | "default_useful_life_months" | "capitalization_threshold" | "inventory_valuation_method" | "review_min_amount" | "review_large_amount" | "calendar" | "date_order" | "number_grouping" | "statement_rounding"
  >;
  can_edit: boolean;
  who_may: { set_up: string[]; change: string[] };
  depreciation_posted: boolean;
  locked_fields: PolicyField[];
  options: {
    accounting_frameworks: string[];
    countries: Option[];
    currencies: Option[];
    months: Option<number>[];
    tax_regimes: Option[];
    depreciation_methods: Option[];
    depreciation_starts: Option[];
    inventory_methods: Option[];
    calendars: Option<Calendar>[];
    date_orders: Option<DateOrder>[];
    number_groupings: Option<NumberGrouping>[];
    roundings: Option<StatementRounding>[];
    country_profiles: CountryProfile[];
    /** A framework that belongs to one country only (for example "Ind AS": "IN"). */
    framework_countries: Record<string, string>;
    /** LIFO is allowed only for a United States company under one of these. */
    lifo_frameworks: string[];
  };
  labels: Record<PolicyField, string>;
  used_by: Record<PolicyField, string>;
  rule_sets: PolicyRuleSet[];
  /** The profile of the company's country, once the policy is set up. */
  country: CountryProfile | null;
}

export interface PolicySaved extends PolicyView {
  changed: PolicyField[];
}

// ── fiscal years and periods (GET / POST /companies/:id/fiscal-year) ──
export interface FiscalYearInfo {
  start: string;
  end: string;
  label: string;
  calendar: Calendar;
  start_month: number;
}

export interface PlannedPeriod {
  label: string;
  start: string;
  end: string;
  bs_start?: string;
  bs_end?: string;
}

export interface FiscalYearPreview {
  fiscal_year: FiscalYearInfo;
  split: "MONTHLY" | "YEARLY";
  calendar: Calendar;
  periods: PlannedPeriod[];
  clashes: { new: string; existing: string; existing_start: string; existing_end: string }[];
  can_create: boolean;
  warnings: string[];
}

export interface FiscalYearCreated {
  fiscal_year: FiscalYearInfo;
  created: number;
  ids: string[];
  periods: PlannedPeriod[];
}