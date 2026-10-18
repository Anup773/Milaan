"use client";

import { useWorkspace } from "@/lib/workspace";
import { signOut } from "@/lib/api-client";
import { ROLE_LABEL } from "@/lib/roles";
import { formatDate } from "@/lib/format";
import { Select } from "@/components/ui/form";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

export function Topbar({ onMenu }: { onMenu: () => void }) {
  const { me, companies, company, periods, period, setCompanyId, setPeriodId } = useWorkspace();

  return (
    <header className="sticky top-0 z-30 flex flex-wrap items-center gap-3 border-b border-rule bg-card/95 px-4 py-2.5 backdrop-blur sm:px-6">
      <button
        type="button"
        onClick={onMenu}
        aria-label="Open menu"
        className="rounded-md p-2 text-ink-soft hover:bg-paper lg:hidden"
      >
        <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" aria-hidden>
          <path d="M3 5h14M3 10h14M3 15h14" />
        </svg>
      </button>

      <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2">
        <label className="sr-only" htmlFor="company-switch">
          Company
        </label>
        <Select
          id="company-switch"
          className="h-9 w-auto max-w-[14rem] font-medium"
          value={company?.id ?? ""}
          onChange={(e) => setCompanyId(e.target.value)}
          disabled={companies.length === 0}
        >
          {companies.length === 0 ? <option value="">No company</option> : null}
          {companies.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </Select>

        <label className="sr-only" htmlFor="period-switch">
          Accounting period
        </label>
        <Select
          id="period-switch"
          className="h-9 w-auto max-w-[16rem]"
          value={period?.id ?? ""}
          onChange={(e) => setPeriodId(e.target.value)}
          disabled={periods.length === 0}
        >
          {periods.length === 0 ? <option value="">No period</option> : null}
          {periods.map((p) => (
            <option key={p.id} value={p.id}>
              {p.label} ({formatDate(p.period_start)} - {formatDate(p.period_end)}){p.lock_status === "LOCKED" ? " - locked" : ""}
            </option>
          ))}
        </Select>
        {period ? <Badge tone={period.lock_status === "LOCKED" ? "ledger" : "pass"}>{period.lock_status === "LOCKED" ? "Period locked" : "Period open"}</Badge> : null}
      </div>

      <div className="flex items-center gap-3">
        {me ? (
          <div className="hidden text-right leading-tight sm:block">
            <div className="max-w-[14rem] truncate text-sm font-medium text-ink">{me.email ?? "Signed in"}</div>
            <div className="text-xs text-ink-faint">{ROLE_LABEL[me.role]}</div>
          </div>
        ) : null}
        <Button variant="secondary" size="sm" onClick={() => void signOut()}>
          Sign out
        </Button>
      </div>
    </header>
  );
}
