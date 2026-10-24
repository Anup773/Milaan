// Shapes returned by the /bank API routes.
import type { ImportIssue } from "./types";

export interface BankStats {
  transactions: number;
  deposits: number;
  withdrawals: number;
  total_deposits: string;
  total_withdrawals: string;
  net_movement: string;
  opening_balance: string | null;
  closing_balance: string | null;
  first_date: string | null;
  last_date: string | null;
  balance_check: "passed" | "failed" | "not_checked";
  balance_mismatches: number;
  order: "oldest_first" | "newest_first";
  skipped_rows: number;
  unreadable_rows: number;
  duplicates: number;
}

export interface BankResult {
  sourceFileId?: string; // present after an import, absent for a check
  rows: number;
  errors: number;
  warnings: number;
  total_debit: string;
  total_credit: string;
  issues_total: number;
  issues: ImportIssue[];
  bank: BankStats;
  preview: boolean;
}