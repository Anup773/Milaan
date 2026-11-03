"use client";

import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Notice } from "@/components/common/notice";
import { api, errorMessage } from "@/lib/api-client";
import { parsePaste } from "@/lib/tax-dep-paste";
import type { TaxSchedule } from "@/lib/tax-dep-types";

const COLUMNS: Record<TaxSchedule["scheme"], string> = {
  NP: "kind, pool, date, amount, description, then: life_years (pool E) | for an opening balance: deferred, accumulated | for a disposal: yes if the pool closes",
  IN: "kind, pool (block), date, amount, description, then: yes if the block ceases (a sale)",
  US: "kind, pool (class, like 5-year), date, amount, description, then: asset_ref, section_179, bonus_percent (a sale: asset_ref)",
};

/** Paste rows from a spreadsheet; all are saved or none. */
export function PasteBox({ companyId, schedule, onDone }: { companyId: string; schedule: TaxSchedule; onDone: () => void }) {
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const parsed = useMemo(() => (text.trim() ? parsePaste(text, schedule.scheme, schedule.calendar) : null), [text, schedule.scheme, schedule.calendar]);

  async function save() {
    if (!parsed || parsed.errors.length > 0) return;
    setBusy(true);
    setError(null);
    try {
      await api(`companies/${companyId}/tax-depreciation/movements/bulk`, { method: "POST", body: { rows: parsed.rows } });
      setText("");
      onDone();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-3">
      <p className="text-sm text-ink-soft">
        Copy rows from Excel or Google Sheets and paste them here. Columns: {COLUMNS[schedule.scheme]}.{" "}
        {schedule.calendar === "BS" ? "Write dates in BS (2082-04-01)." : "Write dates as year-month-day (2025-04-01)."} All rows are added together or none are.
      </p>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={6}
        spellCheck={false}
        aria-label="Rows to paste"
        className="w-full rounded-md border border-rule bg-card p-3 font-mono text-xs text-ink focus:border-ledger focus:outline-none"
      />
      {parsed && parsed.errors.length > 0 ? (
        <Notice kind="error">
          <ul className="list-disc space-y-0.5 pl-5">
            {parsed.errors.slice(0, 8).map((e) => (
              <li key={e}>{e}</li>
            ))}
          </ul>
        </Notice>
      ) : null}
      {parsed && parsed.errors.length === 0 ? <Notice kind="info">{parsed.rows.length} row{parsed.rows.length === 1 ? "" : "s"} ready to add.</Notice> : null}
      {error ? <Notice kind="error">{error}</Notice> : null}
      <Button onClick={save} loading={busy} disabled={!parsed || parsed.errors.length > 0 || parsed.rows.length === 0}>
        Add these rows
      </Button>
    </div>
  );
}