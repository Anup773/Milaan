"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useRef, useState } from "react";
import { PageHeader } from "@/components/common/page-header";
import { Gate } from "@/components/common/gate";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Field, Select, Textarea } from "@/components/ui/form";
import { Modal } from "@/components/ui/modal";
import { Table, TableWrap, Td, Th } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { StatusBadge } from "@/components/common/status";
import { Loading, Notice } from "@/components/common/notice";
import { Money, Delta } from "@/components/common/money";
import { Who } from "@/components/common/who";
import { ImpactTable } from "@/components/simulator/ImpactTable";
import { OverrideEditor, overridesFrom, type OverrideRow } from "@/components/simulator/OverrideEditor";
import { DrillDown } from "@/components/ledger/DrillDown";
import { api, errorMessage } from "@/lib/api-client";
import { useApi } from "@/lib/use-api";
import { CAN, can, type Role } from "@/lib/roles";
import { formatDate, formatDateTime, humanise } from "@/lib/format";
import type { Adjustment, Graph, ReconResult, Scenario, ScenarioImpact } from "@/lib/types";

// Each step the scenario state machine can offer (engine/scenarios/state_machine.py), the API route it posts to, who may take it
// (api/src/modules/scenarios/routes.ts) and whether it needs a written note.
interface StepDef {
  label: string;
  route: string;
  roles: readonly Role[];
  note: "none" | "optional" | "required";
  field?: string; // body field the note is sent in
  help: string;
  variant?: "primary" | "secondary" | "danger";
  extra?: Record<string, unknown>;
}

const STEPS: Record<string, StepDef> = {
  simulate: { label: "Run the simulation", route: "simulate", roles: CAN.makeScenario, note: "none", help: "Calculate the impact of the changes against the current ledger.", variant: "primary" },
  revise: { label: "Revise (back to draft)", route: "revise", roles: CAN.makeScenario, note: "none", help: "Return to draft so the changes can be edited. The simulation is cleared." },
  submit: { label: "Submit for review", route: "submit", roles: CAN.makeScenario, note: "none", help: "Send it to a second person for review. Reconciliation runs first and any error stops it.", variant: "primary" },
  discard: { label: "Discard", route: "discard", roles: CAN.makeScenario, note: "optional", field: "note", help: "Throw this scenario away. It stays on record but can no longer move forward.", variant: "danger" },
  approve: { label: "Approve", route: "approve", roles: CAN.reviewScenario, note: "optional", field: "note", help: "Approve the scenario. You cannot approve one you created yourself.", variant: "primary" },
  reject: { label: "Reject", route: "reject", roles: CAN.reviewScenario, note: "required", field: "note", help: "Send it back to draft with a note saying what has to change.", variant: "danger" },
  post: { label: "Post", route: "post", roles: CAN.linkOrPostScenario, note: "none", help: "Post the scenario. It needs at least one approved adjustment linked, because a scenario reaches the ledger only through adjustments.", variant: "primary" },
  finalize: { label: "Finalise and lock the period", route: "finalize", roles: CAN.finalizeScenario, note: "none", help: "Finalise the scenario and lock the accounting period. After this the period can only be reopened through a reviewed request.", variant: "primary" },
  request_reopen: { label: "Request reopening", route: "reopen-request", roles: CAN.requestReopen, note: "required", field: "reason", help: "Ask for the locked period to be reopened. Give the reason." },
  approve_reopen: { label: "Approve reopening", route: "reopen-decision", roles: CAN.decideReopen, note: "optional", field: "note", help: "Reopen the period. The locked version is kept and a new draft version is created. You cannot decide a request you made yourself.", variant: "primary", extra: { decision: "approve" } },
  deny_reopen: { label: "Deny reopening", route: "reopen-decision", roles: CAN.decideReopen, note: "required", field: "note", help: "Keep the period locked. Say why.", variant: "danger", extra: { decision: "deny" } },
};

const STEP_ORDER = ["simulate", "submit", "approve", "post", "finalize", "revise", "request_reopen", "approve_reopen", "reject", "deny_reopen", "discard"];

function StepDialog({ companyId, scenarioId, step, onClose, onDone }: { companyId: string; scenarioId: string; step: string | null; onClose: () => void; onDone: (step: string) => void }) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const def = step ? STEPS[step] : null;

  async function submit() {
    if (!def || !step) return;
    setBusy(true);
    setError(null);
    try {
      const body: Record<string, unknown> = { ...(def.extra ?? {}) };
      if (def.note !== "none" && note.trim() && def.field) body[def.field] = note.trim();
      await api(`companies/${companyId}/scenarios/${scenarioId}/${def.route}`, { method: "POST", body });
      setNote("");
      onDone(step);
      onClose();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open={def !== null}
      onClose={onClose}
      title={def?.label ?? ""}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button variant={def?.variant === "danger" ? "danger" : "primary"} loading={busy} disabled={def?.note === "required" && !note.trim()} onClick={() => void submit()}>
            {def?.label}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <p className="text-sm text-ink-soft">{def?.help}</p>
        {def && def.note !== "none" ? (
          <Field label={def.note === "required" ? "Note (required)" : "Note (optional)"} htmlFor="step-note">
            <Textarea id="step-note" value={note} onChange={(e) => setNote(e.target.value)} />
          </Field>
        ) : null}
        {error ? <Notice kind="error">{error}</Notice> : null}
      </div>
    </Modal>
  );
}

function ReconList({ results }: { results: ReconResult[] }) {
  const order = ["ERROR", "WARNING", "PASS", "NOT_CHECKED"];
  const sorted = [...results].sort((a, b) => order.indexOf(a.status) - order.indexOf(b.status));
  return (
    <ul className="divide-y divide-rule/70">
      {sorted.map((r) => (
        <li key={r.rule_id} className="flex flex-wrap items-start gap-3 px-5 py-2.5 text-sm">
          <span className="w-28 shrink-0">
            <StatusBadge status={r.status} />
          </span>
          <span className="min-w-0 flex-1">
            <span className="font-medium">{r.title}</span>
            <span className="block text-ink-soft">{r.message}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}

function EditChanges({ companyId, scenario, onSaved }: { companyId: string; scenario: Scenario; onSaved: () => void }) {
  const graph = useApi<Graph>(`companies/${companyId}/dependency-graph`, { periodId: scenario.accounting_period_id });
  const counter = useRef(1000);
  const initial: OverrideRow[] = Object.entries(scenario.overrides).map(([nodeId, amount], i) => ({ key: i + 1, nodeId, amount }));
  const [rows, setRows] = useState<OverrideRow[]>(initial.length > 0 ? initial : [{ key: 1, nodeId: "", amount: "" }]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const parsed = overridesFrom(rows);

  async function save() {
    if (!("overrides" in parsed)) return setError(parsed.error);
    setBusy(true);
    setError(null);
    try {
      await api(`companies/${companyId}/scenarios/${scenario.id}/overrides`, { method: "PUT", body: { overrides: parsed.overrides } });
      onSaved();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader title="Edit the changes" description="Only a draft can be edited. Run the simulation again afterwards." />
      <CardBody className="space-y-4">
        {graph.loading && !graph.data ? <Loading /> : null}
        {graph.error ? <Notice kind="error">{graph.error}</Notice> : null}
        {graph.data ? <OverrideEditor nodes={graph.data.nodes} rows={rows} onChange={setRows} nextKey={() => ++counter.current} /> : null}
        <Button loading={busy} onClick={() => void save()} disabled={!("overrides" in parsed)}>
          Save changes
        </Button>
        {error ? <Notice kind="error">{error}</Notice> : null}
      </CardBody>
    </Card>
  );
}

function LinkAdjustment({ companyId, scenario, onLinked }: { companyId: string; scenario: Scenario; onLinked: () => void }) {
  const adjustments = useApi<{ adjustments: Adjustment[] }>(`companies/${companyId}/adjustments`);
  const [adjustmentId, setAdjustmentId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const linked = new Set(scenario.linked_adjustments.map((a) => String((a as Record<string, unknown>).adjustment_id)));
  const choices = (adjustments.data?.adjustments ?? []).filter(
    (a) => a.accounting_period_id === scenario.accounting_period_id && a.status === "POSTED" && !linked.has(a.id),
  );

  async function link() {
    setBusy(true);
    setError(null);
    try {
      await api(`companies/${companyId}/scenarios/${scenario.id}/adjustments`, { method: "POST", body: { adjustmentId } });
      setAdjustmentId("");
      onLinked();
      adjustments.reload();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-2">
        <Field label="Link an approved adjustment" htmlFor="link-adjustment" className="min-w-[18rem] flex-1" hint="A scenario reaches the ledger only through approved adjustments.">
          <Select id="link-adjustment" value={adjustmentId} onChange={(e) => setAdjustmentId(e.target.value)}>
            <option value="">{choices.length === 0 ? "No approved adjustment available" : "Choose..."}</option>
            {choices.map((a) => (
              <option key={a.id} value={a.id}>
                {formatDate(a.entry_date)} - {a.description}
              </option>
            ))}
          </Select>
        </Field>
        <Button variant="secondary" loading={busy} disabled={!adjustmentId} onClick={() => void link()}>
          Link
        </Button>
      </div>
      {error ? <Notice kind="error">{error}</Notice> : null}
    </div>
  );
}

function Detail({ companyId, scenarioId, role }: { companyId: string; scenarioId: string; role: Role }) {
  const scenario = useApi<Scenario>(`companies/${companyId}/scenarios/${scenarioId}`);
  const impact = useApi<ScenarioImpact>(scenario.data && scenario.data.status !== "DISCARDED" && scenario.data.simulation ? `companies/${companyId}/scenarios/${scenarioId}/impact` : null);
  const graph = useApi<Graph>(scenario.data ? `companies/${companyId}/dependency-graph` : null, { periodId: scenario.data?.accounting_period_id });
  const [step, setStep] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [drill, setDrill] = useState<{ id: string; label: string } | null>(null);

  if (scenario.loading && !scenario.data) return <Loading />;
  if (scenario.error) return <Notice kind="error">{scenario.error}</Notice>;
  const s = scenario.data;
  if (!s) return null;

  const nodeLabel = (id: string) => graph.data?.nodes.find((n) => n.id === id)?.label ?? id;
  const changes = ((s.simulation?.changes as Array<{ node: string; label: string; before: string; after: string; delta: string }> | undefined) ?? []).filter((c) => c.node in s.overrides);
  const recon = s.simulation?.reconciliation as { results?: ReconResult[] } | undefined;
  const offered = STEP_ORDER.filter((a) => s.available_actions.includes(a));
  const locked = s.period_lock_status === "LOCKED";

  function done(taken: string) {
    setMessage(`${STEPS[taken]?.label ?? humanise(taken)}: done.`);
    scenario.reload();
    impact.reload();
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader
          title={s.title}
          description={s.description || undefined}
          actions={
            <>
              <Badge>v{s.version}</Badge>
              <StatusBadge status={s.status} />
              {locked ? <Badge tone="ledger">Period locked</Badge> : null}
            </>
          }
        />
        <CardBody className="space-y-2 text-sm text-ink-soft">
          <div>
            Created by <Who id={s.created_by} /> on {formatDateTime(s.created_at)}
          </div>
          {s.reviewed_by ? (
            <div>
              Reviewed by <Who id={s.reviewed_by} /> on {formatDateTime(s.reviewed_at)}
              {s.review_note ? ` - "${s.review_note}"` : ""}
            </div>
          ) : null}
          {s.finalized_by ? (
            <div>
              Finalised by <Who id={s.finalized_by} /> on {formatDateTime(s.finalized_at)}
            </div>
          ) : null}
          {s.reopen_requested_by ? (
            <div>
              Reopening requested by <Who id={s.reopen_requested_by} /> - &ldquo;{s.reopen_reason}&rdquo;
            </div>
          ) : null}
          {s.superseded_by ? (
            <div>
              Replaced by a newer version:{" "}
              <Link className="font-medium text-ledger underline" href={`/simulator/${s.superseded_by}`}>
                open it
              </Link>
            </div>
          ) : null}
          {s.supersedes_id ? (
            <div>
              Replaces an earlier version:{" "}
              <Link className="font-medium text-ledger underline" href={`/simulator/${s.supersedes_id}`}>
                open it
              </Link>
            </div>
          ) : null}
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="What to do next" description="Only the steps the process allows from here are shown" />
        <CardBody className="space-y-4">
          {message ? <Notice kind="success">{message}</Notice> : null}
          {offered.length === 0 ? <p className="text-sm text-ink-soft">No further step is possible for this scenario.</p> : null}
          <div className="flex flex-wrap gap-2">
            {offered.map((a) => {
              const def = STEPS[a];
              const allowed = can(role, def.roles);
              return (
                <span key={a} className="inline-flex flex-col items-start gap-1">
                  <Button variant={def.variant ?? "secondary"} onClick={() => setStep(a)} disabled={!allowed} title={allowed ? undefined : "Your role cannot take this step"}>
                    {def.label}
                  </Button>
                  {!allowed ? <span className="text-xs text-ink-faint">Not for your role</span> : null}
                </span>
              );
            })}
          </div>
          <p className="text-xs text-ink-faint">The person who made something cannot also approve it. The system refuses that and tells you so.</p>
          {s.status === "APPROVED" && can(role, CAN.linkOrPostScenario) ? <LinkAdjustment companyId={companyId} scenario={s} onLinked={scenario.reload} /> : null}
        </CardBody>
      </Card>

      {s.status === "DRAFT" && can(role, CAN.makeScenario) ? <EditChanges companyId={companyId} scenario={s} onSaved={() => { setMessage("Changes saved. Run the simulation to see the impact."); scenario.reload(); }} /> : null}

      <Card>
        <CardHeader title="The changes" description="The figures this scenario overrides" />
        <TableWrap>
          <Table>
            <thead>
              <tr>
                <Th>Figure</Th>
                <Th align="right">Current</Th>
                <Th align="right">New value</Th>
                <Th align="right">Change</Th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(s.overrides).map(([node, value]) => {
                const c = changes.find((x) => x.node === node);
                return (
                  <tr key={node}>
                    <Td className="font-medium">{c?.label ?? nodeLabel(node)}</Td>
                    <Td align="right">{c ? <Money value={c.before} /> : "-"}</Td>
                    <Td align="right">
                      <Money value={value} />
                    </Td>
                    <Td align="right">{c ? <Delta value={c.delta} goodWhen="neutral" /> : "-"}</Td>
                  </tr>
                );
              })}
            </tbody>
          </Table>
        </TableWrap>
      </Card>

      {impact.loading && !impact.data && s.simulation ? <Loading label="Working out the impact..." /> : null}
      {impact.error ? <Notice kind="error">{impact.error}</Notice> : null}
      {impact.data ? (
        <div className="space-y-3">
          <h2 className="text-base font-semibold text-ink">Impact</h2>
          {!impact.data.simulation_current ? <Notice kind="warning">The ledger has changed since this was simulated. Revise and run the simulation again to refresh it.</Notice> : null}
          <ImpactTable
            report={impact.data.report}
            note={impact.data.note}
            onOpenAccount={(row) => {
              const meta = graph.data?.nodes.find((n) => n.id === row.node)?.meta as { account_id?: string } | undefined;
              if (meta?.account_id) setDrill({ id: meta.account_id, label: row.label });
            }}
          />
        </div>
      ) : !s.simulation && s.status !== "DISCARDED" ? (
        <Notice kind="info">This scenario has not been simulated yet. Run the simulation to see its impact.</Notice>
      ) : null}

      {recon?.results && recon.results.length > 0 ? (
        <Card>
          <CardHeader title="Checks on this what-if" description="Reconciliation run on the scenario's figures when it was simulated" />
          <ReconList results={recon.results} />
        </Card>
      ) : null}

      {s.linked_adjustments.length > 0 ? (
        <Card>
          <CardHeader title="Linked adjustments" actions={<Link href="/adjustments" className="text-sm font-medium text-ledger">Open adjustments</Link>} />
          <ul className="divide-y divide-rule/70">
            {s.linked_adjustments.map((a, i) => {
              const row = a as { adjustment_id?: string; status?: string; description?: string };
              return (
                <li key={row.adjustment_id ?? i} className="flex flex-wrap items-center gap-3 px-5 py-2.5 text-sm">
                  <span className="font-medium">{row.description}</span>
                  <StatusBadge status={row.status} />
                </li>
              );
            })}
          </ul>
        </Card>
      ) : null}

      <Card>
        <CardHeader title="History" description="Every step, oldest first" />
        <ol className="divide-y divide-rule/70">
          {s.transitions.map((t, i) => (
            <li key={i} className="flex flex-wrap items-start gap-3 px-5 py-3 text-sm">
              <span className="w-40 shrink-0 text-ink-soft">{formatDateTime(t.at)}</span>
              <span className="font-medium">{humanise(t.action)}</span>
              <span className="text-ink-soft">
                {t.from_status && t.from_status !== t.to_status ? `${humanise(t.from_status)} to ` : ""}
                {humanise(t.to_status)}
              </span>
              <span className="text-ink-soft">
                by <Who id={t.actor_id} />
              </span>
              {t.note ? <span className="basis-full pl-[10.75rem] text-ink">&ldquo;{t.note}&rdquo;</span> : null}
            </li>
          ))}
        </ol>
      </Card>

      <StepDialog companyId={companyId} scenarioId={s.id} step={step} onClose={() => setStep(null)} onDone={done} />
      <DrillDown companyId={companyId} periodId={s.accounting_period_id} accountId={drill?.id ?? null} accountLabel={drill?.label ?? ""} onClose={() => setDrill(null)} />
    </div>
  );
}

export default function ScenarioPage() {
  const params = useParams<{ id: string }>();
  return (
    <>
      <PageHeader title="Scenario" description="One what-if: its changes, its impact, and where it stands in review." actions={<Link href="/simulator" className="text-sm font-medium text-ledger">All scenarios</Link>} />
      <Gate>{({ company, role }) => <Detail key={`${company.id}:${params.id}`} companyId={company.id} scenarioId={params.id} role={role} />}</Gate>
    </>
  );
}
