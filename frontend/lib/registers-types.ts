// Shapes returned by the /registers API routes.
import type { ImportIssue } from "./types";

export interface RegisterRole {
  key: string;
  label: string;
  default: string;
}

export interface RegisterColumn {
  field: string;
  names: string[];
  required: boolean;
}

export interface RegisterTemplate {
  key: string;
  label: string;
  description: string;
  required_columns: string[];
  columns: RegisterColumn[];
  roles: RegisterRole[];
  party_accounts_option: boolean;
}

export interface RegisterTemplates {
  templates: RegisterTemplate[];
}

export interface RegisterSummaryItem {
  label: string;
  value: string;
  kind: "money" | "text";
}

export interface RegisterStats {
  template: string;
  records: number;
  unreadable_rows: number;
  skipped_rows: number;
  duplicates: number;
  round_off_rows: number;
  credit_notes: number;
  first_date: string | null;
  last_date: string | null;
  date_from_default: number;
  summary: RegisterSummaryItem[];
}

export interface RegisterResult {
  sourceFileId?: string; // present after an import, absent for a check
  rows: number;
  errors: number;
  warnings: number;
  total_debit: string;
  total_credit: string;
  issues_total: number;
  issues: ImportIssue[];
  register: RegisterStats;
  preview: boolean;
}