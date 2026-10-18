
"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useRef, useState, type FormEvent } from "react";
import { PageHeader } from "@/components/common/page-header";
import { Gate } from "@/components/common/gate";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Field, Input, Textarea } from "@/components/ui/form";
import { Table, TableWrap, Td, Th } from "@/components/ui/table";
import { StatusBadge } from "@/components/common/status";
import { Empty, Loading, Notice } from "@/components/common/notice";
import { Who } from "@/components/common/who";
import { ImpactTable } from "@/components/simulator/ImpactTable";
import { OverrideEditor, overridesFrom, type OverrideRow } from "@/components/simulator/OverrideEditor";
import { DrillDown } from "@/components/ledger/DrillDown";
import { api, errorMessage } from "@/lib/api-client";
import { useApi } from "@/lib/use-api";
import { CAN, can, type Role } from "@/lib/roles";
import { formatDateTime } from "@/lib/format";
import type { Graph, ImpactPreview, Period, ScenarioListItem } from "@/lib/types";

function Composer({ companyId, period, role }: { companyId: string; period: Period; role: Role }) {
  const router = useRouter();
  const graph = useApi<Graph>(`companies/${companyId}/dependency-graph`, { periodId: period.id });
  const counter = useRef(2);
  const nextKey = () => ++counter.current;
  const [rows, setRows] = useState<OverrideRow[]>([{ key: 1, nodeId: "", amount: "" }]);
  const [preview, setPreview] = useState<ImpactPreview | null>(null);
  const [previewOf, setPreviewOf] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [drill, setDrill] = useState<{ id: string; label: string } | null>(null);

  const parsed = overridesFrom(rows);
  const signature = "overrides" in parsed ? JSON.stringify(parsed.overrides) : "";
  const stale = preview !== null && previewOf !== signature;
  const canMake = can(role, CAN.makeScenario);

  async function runPreview() {
    if (!("overrides" in parsed)) return setError(parsed.error);
    setError(null);
    setBusy(true);
    try {
      const result = await api<ImpactPreview>(`companies/${companyId}/impact/preview`, {
        method: "POST",
        body: { periodId: period.id, overrides: parsed.overrides },
      });
      setPreview(result);
      setPreviewOf(signature);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!("overrides" in parsed)) return setError(parsed.error);
    setError(null);
    setSaving(true);
    try {
      const created = await api<{ scenario_id: string }>(`companies/${companyId}/scenarios`, {
        method: "POST",
        body: { periodId: period.id, title: title.trim(), description: description.trim(), overrides: parsed.overrides },
      });
      router.push(`/simulator/${created.scenario_id}`);
    } catch (err) {
      setError(errorMessage(err));
      setSaving(false);
    }
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader title="Change one thing" description={`Pick a figure in ${period.label}, give it a new value, and see everything it touches. Nothing is saved until you choose to.`} />
        <CardBody className="space-y-4">
          {graph.loading && !graph.data ? <Loading /> : null}
          {graph.error ? <Notice kind="error">{graph.error}</Notice> : null}
          {graph.data ? (
            <>
              <OverrideEditor nodes={graph.data.nodes} rows={rows} onChange={setRows} nextKey={nextKey} />
              <div className="flex flex-wrap items-center gap-3">
                <Button loading={busy} onClick={() => void runPreview()} disabled={!("overrides" in parsed)}>
                  Show the impact
                </Button>
                {"error" in parsed ? <span className="text-sm text-ink-faint">{parsed.error}</span> : null}
              </div>
            </>
          ) : null}
          {error ? <Notice kind="error">{error}</Notice> : null}
        </CardBody>
      </Card>

      {preview ? (
        <div className="space-y-4">
          {stale ? <Notice kind="warning">You changed the figures after this was calculated. Show the impact again to refresh it.</Notice> : null}
          <ImpactTable report={preview.report} note={preview.note} onOpenAccount={(row) => {
            const meta = graph.data?.nodes.find((n) => n.id === row.node)?.meta as { account_id?: string } | undefined;
            if (meta?.account_id) setDrill({ id: meta.account_id, label: row.label });
          }} />
          {canMake ? (
            <Card>
              <CardHeader title="Keep this as a scenario" description="A saved scenario can be reviewed by someone else, approved and, with approved adjustments behind it, posted." />
              <CardBody>
                <form onSubmit={save} className="grid gap-3 sm:grid-cols-2">
                  <Field label="Title" htmlFor="sc-title">
                    <Input id="sc-title" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Depreciation at 54,000" />
                  </Field>
                  <Field label="Notes (optional)" htmlFor="sc-desc" className="sm:row-span-2">
                    <Textarea id="sc-desc" value={description} onChange={(e) => setDescription(e.target.value)} />
                  </Field>
                  <div className="flex items-end">
                    <Button type="submit" loading={saving} disabled={!title.trim() || stale || !("overrides" in parsed)}>
                      Save scenario
                    </Button>
                  </div>
                </form>
              </CardBody>
            </Card>
          ) : (
            <Notice kind="info">Saving a scenario needs an accountant role or above. You can still explore changes freely.</Notice>
          )}
        </div>
      ) : null}

      <DrillDown companyId={companyId} periodId={period.id} accountId={drill?.id ?? null} accountLabel={drill?.label ?? ""} onClose={() => setDrill(null)} />
    </div>
  );
}

function ScenarioList({ companyId, period }: { companyId: string; period: Period }) {
  const { data, error, loading } = useApi<{ scenarios: ScenarioListItem[] }>(`companies/${companyId}/scenarios`);
  const mine = (data?.scenarios ?? []).filter((s) => s.period_id === period.id);
  return (
    <Card>
      <CardHeader title={`Saved scenarios - ${period.label}`} description="Open one to review it, move it along, or see its impact" />
      {error ? (
        <CardBody>
          <Notice kind="error">{error}</Notice>
        </CardBody>
      ) : null}
      {loading && !data ? <Loading /> : null}
      {data && mine.length === 0 ? <Empty title="No scenarios yet for this period">Try a change above and keep it.</Empty> : null}
      {mine.length > 0 ? (
        <TableWrap>
          <Table>
            <thead>
              <tr>
                <Th>Scenario</Th>
                <Th>Version</Th>
                <Th>Status</Th>
                <Th>Created by</Th>
                <Th>Created</Th>
              </tr>
            </thead>
            <tbody>
              {mine.map((s) => (
                <tr key={s.scenario_id}>
                  <Td>
                    <Link href={`/simulator/${s.scenario_id}`} className="font-medium text-ledger-dark underline decoration-ledger/30 underline-offset-2 hover:decoration-ledger">
                      {s.title}
                    </Link>
                    {s.superseded_by ? <span className="ml-2 text-xs text-ink-faint">replaced by a newer version</span> : null}
                  </Td>
                  <Td>v{s.version}</Td>
                  <Td>
                    <StatusBadge status={s.status} />
                  </Td>
                  <Td>
                    <Who id={s.created_by} />
                  </Td>
                  <Td className="whitespace-nowrap text-ink-soft">{formatDateTime(s.created_at)}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </TableWrap>
      ) : null}
    </Card>
  );
}

export default function SimulatorPage() {
  return (
    <>
      <PageHeader title="Simulator" description="Change one figure and see every impact across the profit and loss and the balance sheet, before anything is posted." />
      <Gate needsPeriod>
        {({ company, period, role }) =>
          period ? (
            <div className="space-y-6" key={`${company.id}:${period.id}`}>
              <Composer companyId={company.id} period={period} role={role} />
              <ScenarioList companyId={company.id} period={period} />
            </div>
          ) : null
        }
      </Gate>
    </>
  );
}
