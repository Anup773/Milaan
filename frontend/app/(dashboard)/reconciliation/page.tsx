"use client";

import { useState } from "react";
import { PageHeader } from "@/components/common/page-header";
import { Gate } from "@/components/common/gate";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Table, TableWrap, Td, Th } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { StatusBadge } from "@/components/common/status";
import { Empty, Loading, Notice } from "@/components/common/notice";
import { Who } from "@/components/common/who";
import { api, errorMessage } from "@/lib/api-client";
import { useApi } from "@/lib/use-api";
import { formatDateTime } from "@/lib/format";
import type { CheckStatus, Period, ReconResult, ReconRun, ReconRunSummary } from "@/lib/types";

const ORDER: CheckStatus[] = ["ERROR", "WARNING", "PASS", "NOT_CHECKED"];

function Counts({ counts }: { counts: Record<CheckStatus, number> }) {
  return (
    <div className="flex flex-wrap gap-1.5 text-xs">
      {counts.ERROR ? <Badge tone="fail">{counts.ERROR} error</Badge> : null}
      {counts.WARNING ? <Badge tone="warn">{counts.WARNING} warning</Badge> : null}
      <Badge tone="pass">{counts.PASS} passed</Badge>
      {counts.NOT_CHECKED ? <Badge>{counts.NOT_CHECKED} not checked</Badge> : null}
    </div>
  );
}

function Results({ results }: { results: ReconResult[] }) {
  const sorted = [...results].sort((a, b) => ORDER.indexOf(a.status) - ORDER.indexOf(b.status));
  return (
    <ul className="divide-y divide-rule/70">
      {sorted.map((r) => (
        <li key={r.rule_id} className="flex flex-wrap items-start gap-3 px-5 py-3">
          <div className="w-28 shrink-0 pt-0.5">
            <StatusBadge status={r.status} />
          </div>
          <div className="min-w-0 flex-1">
            <div className="text-sm font-medium text-ink">{r.title}</div>
            <div className="mt-0.5 text-sm text-ink-soft">{r.message}</div>
          </div>
        </li>
      ))}
    </ul>
  );
}

function Reconciliation({ companyId, period }: { companyId: string; period: Period }) {
  const latest = useApi<{ run: ReconRun | null }>(`companies/${companyId}/reconciliation`, { periodId: period.id });
  const runs = useApi<{ runs: ReconRunSummary[] }>(`companies/${companyId}/reconciliation/runs`, { periodId: period.id });
  const [selected, setSelected] = useState<string | null>(null);
  const picked = useApi<ReconRun>(selected ? `companies/${companyId}/reconciliation/runs/${selected}` : null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    setRunning(true);
    setError(null);
    try {
      await api(`companies/${companyId}/reconciliation/run`, { method: "POST", body: { periodId: period.id } });
      setSelected(null);
      latest.reload();
      runs.reload();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setRunning(false);
    }
  }

  const shown = selected ? picked.data : latest.data?.run ?? null;
  const loadingShown = selected ? picked.loading && !picked.data : latest.loading && !latest.data;

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader
          title={selected ? "An earlier run" : "Latest run"}
          description={shown ? `Run ${formatDateTime(shown.run_at)}` : `The checks on ${period.label}, on the books as posted`}
          actions={
            <>
              {selected ? (
                <Button variant="secondary" size="sm" onClick={() => setSelected(null)}>
                  Back to latest
                </Button>
              ) : null}
              <Button size="sm" loading={running} onClick={() => void run()}>
                Run the checks now
              </Button>
            </>
          }
        />
        {error ? (
          <CardBody>
            <Notice kind="error">{error}</Notice>
          </CardBody>
        ) : null}
        {(selected ? picked.error : latest.error) ? (
          <CardBody>
            <Notice kind="error">{selected ? picked.error : latest.error}</Notice>
          </CardBody>
        ) : null}
        {loadingShown ? <Loading /> : null}
        {!loadingShown && !shown && !latest.error ? (
          <Empty title="No run yet for this period">Run the checks to see whether the books agree with themselves.</Empty>
        ) : null}
        {shown ? (
          <>
            <div className="flex flex-wrap items-center gap-3 border-b border-rule px-5 py-3">
              <StatusBadge status={shown.overall_status} />
              <Counts counts={shown.counts} />
              {shown.with_overrides ? <Badge tone="info">Run on a what-if scenario</Badge> : null}
            </div>
            <Results results={shown.results} />
          </>
        ) : null}
      </Card>

      <Card>
        <CardHeader title="History" description="Every saved run is kept; a run is never changed afterwards" />
        {runs.error ? (
          <CardBody>
            <Notice kind="error">{runs.error}</Notice>
          </CardBody>
        ) : null}
        {runs.loading && !runs.data ? <Loading /> : null}
        {runs.data && runs.data.runs.length === 0 ? <Empty title="No saved runs" /> : null}
        {runs.data && runs.data.runs.length > 0 ? (
          <TableWrap>
            <Table>
              <thead>
                <tr>
                  <Th>When</Th>
                  <Th>Result</Th>
                  <Th>Counts</Th>
                  <Th>Run by</Th>
                  <Th>Basis</Th>
                  <Th />
                </tr>
              </thead>
              <tbody>
                {runs.data.runs.map((r) => (
                  <tr key={r.run_id} className={r.run_id === selected ? "bg-ledger-soft/50" : undefined}>
                    <Td className="whitespace-nowrap">{formatDateTime(r.run_at)}</Td>
                    <Td>
                      <StatusBadge status={r.overall_status} />
                    </Td>
                    <Td>
                      <Counts counts={r.counts} />
                    </Td>
                    <Td>
                      <Who id={r.run_by} />
                    </Td>
                    <Td>{r.with_overrides ? "Scenario what-if" : "Books as posted"}</Td>
                    <Td align="right">
                      <Button size="sm" variant="ghost" onClick={() => setSelected(r.run_id)}>
                        View
                      </Button>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </TableWrap>
        ) : null}
      </Card>
    </div>
  );
}

export default function ReconciliationPage() {
  return (
    <>
      <PageHeader title="Reconciliation" description="Checks that the books agree with themselves: debits and credits, the balance sheet, the fixed-asset schedule, uploaded rows and open reviews." />
      <Gate needsPeriod>{({ company, period }) => (period ? <Reconciliation key={`${company.id}:${period.id}`} companyId={company.id} period={period} /> : null)}</Gate>
    </>
  );
}