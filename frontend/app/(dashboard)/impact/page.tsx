"use client";

import Link from "next/link";
import { useState } from "react";
import { PageHeader } from "@/components/common/page-header";
import { Gate } from "@/components/common/gate";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Field, Select } from "@/components/ui/form";
import { Loading, Notice, Empty } from "@/components/common/notice";
import { StatusBadge } from "@/components/common/status";
import { ImpactTable } from "@/components/simulator/ImpactTable";
import { DrillDown } from "@/components/ledger/DrillDown";
import { useApi } from "@/lib/use-api";
import { formatDateTime } from "@/lib/format";
import type { Graph, Period, ScenarioImpact, ScenarioListItem } from "@/lib/types";

function Impact({ companyId, period }: { companyId: string; period: Period }) {
  const list = useApi<{ scenarios: ScenarioListItem[] }>(`companies/${companyId}/scenarios`);
  const usable = (list.data?.scenarios ?? []).filter((s) => s.period_id === period.id && s.status !== "DISCARDED" && s.status !== "DRAFT");
  const [picked, setPicked] = useState("");
  const chosen = usable.some((s) => s.scenario_id === picked) ? picked : (usable[0]?.scenario_id ?? "");
  const impact = useApi<ScenarioImpact>(chosen ? `companies/${companyId}/scenarios/${chosen}/impact` : null);
  const graph = useApi<Graph>(chosen ? `companies/${companyId}/dependency-graph` : null, { periodId: period.id });
  const [drill, setDrill] = useState<{ id: string; label: string } | null>(null);

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader title="Pick a scenario" description={`Scenarios in ${period.label} that have been simulated`} />
        <CardBody>
          {list.error ? <Notice kind="error">{list.error}</Notice> : null}
          {list.loading && !list.data ? <Loading /> : null}
          {list.data && usable.length === 0 ? (
            <Empty title="No simulated scenario in this period">
              Try a change on the{" "}
              <Link href="/simulator" className="font-medium text-ledger underline">
                Simulator
              </Link>
              , save it and run its simulation.
            </Empty>
          ) : null}
          {usable.length > 0 ? (
            <Field label="Scenario" htmlFor="impact-scenario" className="max-w-lg">
              <Select id="impact-scenario" value={chosen} onChange={(e) => setPicked(e.target.value)}>
                {usable.map((s) => (
                  <option key={s.scenario_id} value={s.scenario_id}>
                    {s.title} (v{s.version}, {s.status.toLowerCase().replace(/_/g, " ")})
                  </option>
                ))}
              </Select>
            </Field>
          ) : null}
        </CardBody>
      </Card>

      {impact.loading && !impact.data && chosen ? <Loading label="Working out the impact..." /> : null}
      {impact.error ? <Notice kind="error">{impact.error}</Notice> : null}
      {impact.data ? (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-3">
            <h2 className="text-base font-semibold text-ink">{impact.data.title}</h2>
            <StatusBadge status={impact.data.status} />
            <span className="text-sm text-ink-soft">{impact.data.basis === "live" ? "Live against the current ledger" : "Frozen at posting"}</span>
            {impact.data.simulated_at ? <span className="text-sm text-ink-faint">Simulated {formatDateTime(impact.data.simulated_at)}</span> : null}
            <Link href={`/simulator/${impact.data.scenario_id}`} className="text-sm font-medium text-ledger">
              Open the scenario
            </Link>
          </div>
          {!impact.data.simulation_current && impact.data.basis === "live" ? (
            <Notice kind="warning">The ledger has changed since this was simulated, so the figures may be out of date. Revise the scenario and simulate again.</Notice>
          ) : null}
          <ImpactTable
            report={impact.data.report}
            note={impact.data.note}
            onOpenAccount={(row) => {
              const meta = graph.data?.nodes.find((n) => n.id === row.node)?.meta as { account_id?: string } | undefined;
              if (meta?.account_id) setDrill({ id: meta.account_id, label: row.label });
            }}
          />
        </div>
      ) : null}
      <DrillDown companyId={companyId} periodId={period.id} accountId={drill?.id ?? null} accountLabel={drill?.label ?? ""} onClose={() => setDrill(null)} />
    </div>
  );
}

export default function ImpactPage() {
  return (
    <>
      <PageHeader title="Impact" description="For a saved scenario: every figure it changes, current against scenario, from the inputs through the profit and loss to the balance sheet." />
      <Gate needsPeriod>{({ company, period }) => (period ? <Impact key={`${company.id}:${period.id}`} companyId={company.id} period={period} /> : null)}</Gate>
    </>
  );
}