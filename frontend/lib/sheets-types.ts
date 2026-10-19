// Shapes returned by the /sheets API routes.
import type { ImportResult } from "./types";

export interface SheetsStatus {
  mode: "service_account" | "public_link" | "service_account_error";
  service_account_email: string | null;
  message: string;
}

export interface SheetTab {
  title: string;
  gid: number;
}

export interface SheetCheck {
  mode: "service_account" | "public_link";
  title: string | null;
  tabs: SheetTab[];
  suggested_tab: string | null;
  rows_seen?: number;
  gid?: number;
}

export interface SheetsImportResult extends ImportResult {
  sheet: { mode: string; title: string | null; tab: string | null; label: string };
}