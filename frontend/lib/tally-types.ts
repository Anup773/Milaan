// Shapes returned by the /tally API routes.
import type { ImportResult } from "./types";

export interface TallyStatus {
  reachable: boolean;
  url: string | null;
  companies: string[];
  message: string;
}

export interface TallyStats {
  vouchers_seen: number;
  vouchers_imported: number;
  skipped_cancelled: number;
  skipped_optional: number;
  skipped_non_accounting: number;
  skipped_no_ledger_lines: number;
  zero_amount_lines_skipped: number;
  unbalanced_vouchers: number;
  first_date: string | null;
  last_date: string | null;
}

export interface TallyImportResult extends ImportResult {
  tally: TallyStats;
}