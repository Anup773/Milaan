"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { PageHeader } from "@/components/common/page-header";
import { Gate } from "@/components/common/gate";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { StatusBadge } from "@/components/common/status";
import { Money } from "@/components/common/money";
import { Notice } from "@/components/common/notice";
import { useApi } from "@/lib/use-api";
import { formatDateTime } from "@/lib/format";
import type {
  Adjustment,
  ApprovalSummary,
  BalanceSheet,
  ExceptionSummary,
  ProfitLoss,
  ReconRun,
  ScenarioListItem,
} from "@/lib/types";

function Tile({ label, children, href }: { label: string; children: ReactNode; href: string }) {
  return (
    <Link href={href} className="block rounded-lg border border-rule bg-card px-4 py-3.5 transition-colors hover:border-ledger">
      <div className="text-xs font-medium uppercase tracking-wide text-ink-faint">{label}</div>
      <div className="mt-1 text-xl font-semibold text-ink">{children}</div>
    </Link>
  );
}

function OpenLink({ href, children = "Open" }: { href: string; children?: ReactNode }) {
  return (
    <Link className="text-sm font-medium text-ledger" href={href}>
      {children}
    </Link>
  );
}

function Dash({ companyId, periodId, periodEnd, periodLabel }: { companyId: string; periodId: string; periodEnd: string; periodLabel: string }) {
  const base = `companies/${companyId}`;
  const pl = useApi<ProfitLoss>(`${base}/statements/profit-loss`, { periodId });
  const bs = useApi<BalanceSheet>(`${base}/statements/balance-sheet`, { asOfDate: periodEnd });
  const exc = useApi<ExceptionSummary>(`${base}/exceptions/summary`, { periodId });
  const rec = useApi<{ run: ReconRun | null }>(`${base}/reconciliation`, { periodId });
  const adj = useApi<{ adjustments: Adjustment[] }>(`${base}/adjustments`);
  const scn = useApi<{ scenarios: ScenarioListItem[] }>(`${base}/scenarios`);
  const apr = useApi<ApprovalSummary>(`${base}/approvals/summary`, { periodId });

  const adjustmentsWaiting = adj.data
    ? adj.data.adjustments.filter((a) => a.accounting_period_id === periodId && a.status === "REVIEW_REQUIRED").length
    : null;
  const scenariosInPeriod = scn.data ? scn.data.scenarios.filter((s) => s.period_id === periodId && s.status !== "DISCARDED") : null;
  const run = rec.data?.run ?? null;

  return (
    <div className="space-y-8">
      <section aria-labelledby="fo">
        <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
          <h2 id="fo" className="text-base font-semibold text-ink">
            Financial overview
          </h2>
          <span className="text-sm text-ink-soft">{periodLabel}, live from the ledger</span>
        </div>
        {pl.error || bs.error ? <Notice kind="error" className="mb-3">{pl.error ?? bs.error}</Notice> : null}
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <Tile label="Revenue" href="/statements?tab=pl">
            <Money value={pl.data?.total_income} />
          </Tile>
          <Tile label="Expenses" href="/statements?tab=pl">
            <Money value={pl.data?.total_expense} />
          </Tile>
          <Tile label="Profit" href="/statements?tab=pl">
            <Money value={pl.data?.net_profit} />
          </Tile>
          <Tile label="Assets" href="/statements?tab=bs">
            <Money value={bs.data?.total_assets} />
          </Tile>
          <Tile label="Liabilities" href="/statements?tab=bs">
            <Money value={bs.data?.total_liabilities} />
          </Tile>
        </div>
        <p className="mt-2 text-xs text-ink-faint">
          Every figure opens the statement behind it. Click an account there to see the ledger lines and the file row each one came from.
        </p>
      </section>

      <section aria-labelledby="fw">
        <h2 id="fw" className="mb-3 text-base font-semibold text-ink">
          Finalisation workspace
        </h2>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <Card>
            <CardHeader title="Exceptions" description="Entries a detector or a person flagged" actions={<OpenLink href="/exceptions" />} />
            <CardBody>
              {exc.error ? (
                <Notice kind="error">{exc.error}</Notice>
              ) : (
                <>
                  <div className="num text-2xl font-semibold text-ink">{exc.data ? exc.data.open_total : "-"}</div>
                  <div className="mt-1 text-sm text-ink-soft">open for review</div>
                  {exc.data && exc.data.open_total > 0 ? (
                    <div className="mt-3 flex flex-wrap gap-1.5">
                      {(["HIGH", "MEDIUM", "LOW"] as const).map((p) =>
                        exc.data!.open_by_priority[p] ? (
                          <Badge key={p} tone={p === "HIGH" ? "fail" : p === "MEDIUM" ? "warn" : "neutral"}>
                            {exc.data!.open_by_priority[p]} {p.toLowerCase()}
                          </Badge>
                        ) : null,
                      )}
                    </div>
                  ) : null}
                  {exc.data && !exc.data.last_run ? (
                    <p className="mt-3 text-xs text-ink-faint">Detection has not been run for this period.</p>
                  ) : null}
                </>
              )}
            </CardBody>
          </Card>

          <Card>
            <CardHeader title="Reconciliation" description="The latest saved run of the checks" actions={<OpenLink href="/reconciliation" />} />
            <CardBody>
              {rec.error ? (
                <Notice kind="error">{rec.error}</Notice>
              ) : run ? (
                <>
                  <StatusBadge status={run.overall_status} />
                  <div className="mt-3 flex flex-wrap gap-1.5 text-xs">
                    {run.counts.ERROR ? <Badge tone="fail">{run.counts.ERROR} error</Badge> : null}
                    {run.counts.WARNING ? <Badge tone="warn">{run.counts.WARNING} warning</Badge> : null}
                    <Badge tone="pass">{run.counts.PASS} passed</Badge>
                    {run.counts.NOT_CHECKED ? <Badge>{run.counts.NOT_CHECKED} not checked</Badge> : null}
                  </div>
                  <p className="mt-3 text-xs text-ink-faint">Run {formatDateTime(run.run_at)}</p>
                </>
              ) : (
                <p className="text-sm text-ink-soft">{rec.loading ? "Loading..." : "No run yet for this period."}</p>
              )}
            </CardBody>
          </Card>

          <Card>
            <CardHeader title="Adjustment proposals" description="Waiting for a second person" actions={<OpenLink href="/adjustments" />} />
            <CardBody>
              {adj.error ? (
                <Notice kind="error">{adj.error}</Notice>
              ) : (
                <>
                  <div className="num text-2xl font-semibold text-ink">{adjustmentsWaiting ?? "-"}</div>
                  <div className="mt-1 text-sm text-ink-soft">waiting for approval</div>
                </>
              )}
            </CardBody>
          </Card>

          <Card>
            <CardHeader title="Scenarios" description="What-ifs for this period" actions={<OpenLink href="/simulator" />} />
            <CardBody>
              {scn.error ? (
                <Notice kind="error">{scn.error}</Notice>
              ) : (
                <>
                  <div className="num text-2xl font-semibold text-ink">{scenariosInPeriod ? scenariosInPeriod.length : "-"}</div>
                  <div className="mt-1 text-sm text-ink-soft">not discarded</div>
                  {scenariosInPeriod && scenariosInPeriod.length > 0 ? (
                    <div className="mt-3 flex flex-wrap gap-2">
                      {Array.from(new Set(scenariosInPeriod.map((s) => s.status))).map((status) => (
                        <span key={status} className="inline-flex items-center gap-1">
                          <StatusBadge status={status} />
                          <span className="text-xs text-ink-soft">{scenariosInPeriod.filter((s) => s.status === status).length}</span>
                        </span>
                      ))}
                    </div>
                  ) : null}
                </>
              )}
            </CardBody>
          </Card>

          <Card>
            <CardHeader title="Approvals" description="Decisions waiting in this period" actions={<OpenLink href="/approvals" />} />
            <CardBody>
              {apr.error ? (
                <Notice kind="error">{apr.error}</Notice>
              ) : (
                <>
                  <div className="num text-2xl font-semibold text-ink">{apr.data ? apr.data.waiting_for_you : "-"}</div>
                  <div className="mt-1 text-sm text-ink-soft">waiting for you</div>
                  {apr.data ? (
                    <p className="mt-3 text-xs text-ink-faint">
                      {apr.data.waiting_total} waiting in all, {apr.data.waiting_on_others} on others
                    </p>
                  ) : null}
                </>
              )}
            </CardBody>
          </Card>

          <Card>
            <CardHeader title="Approved items" description="Decisions already taken" actions={<OpenLink href="/approvals">History</OpenLink>} />
            <CardBody>
              {apr.error ? (
                <Notice kind="error">{apr.error}</Notice>
              ) : (
                <>
                  <div className="num text-2xl font-semibold text-ink">{apr.data ? (apr.data.decided.total_by_outcome.APPROVED ?? 0) : "-"}</div>
                  <div className="mt-1 text-sm text-ink-soft">approved</div>
                  {apr.data ? (
                    <p className="mt-3 text-xs text-ink-faint">
                      {apr.data.decided.total_by_outcome.REJECTED ?? 0} rejected, {apr.data.decided.total_by_outcome.FINALIZED ?? 0} finalised
                    </p>
                  ) : null}
                </>
              )}
            </CardBody>
          </Card>
        </div>
      </section>
    </div>
  );
}

export default function DashboardPage() {
  return (
    <>
      <PageHeader title="Dashboard" description="Where the books stand, and what still needs a person before the period can be finalised." />
      <Gate needsPeriod>
        {({ company, period }) =>
          period ? (
            <Dash key={`${company.id}:${period.id}`} companyId={company.id} periodId={period.id} periodEnd={period.period_end} periodLabel={period.label} />
          ) : null
        }
      </Gate>
    </>
  );
}