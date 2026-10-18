"use client";

import { useState } from "react";
import Link from "next/link";
import { PageHeader } from "@/components/common/page-header";
import { Gate } from "@/components/common/gate";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Field, Select, Textarea } from "@/components/ui/form";
import { Modal } from "@/components/ui/modal";
import { Tabs } from "@/components/ui/tabs";
import { Table, TableWrap, Td, Th } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { StatusBadge } from "@/components/common/status";
import { Empty, Loading, Notice } from "@/components/common/notice";
import { Money } from "@/components/common/money";
import { Stat } from "@/components/common/stat";
import { Who } from "@/components/common/who";
import { api, errorMessage } from "@/lib/api-client";
import { useApi } from "@/lib/use-api";
import { formatDate, formatDateTime, humanise } from "@/lib/format";
import type {
  ApprovalHistory,
  ApprovalInbox,
  ApprovalItem,
  ApprovalKind,
  ApprovalSummary,
  People,
  Period,
  ReconResult,
} from "@/lib/types";

const KIND_LABEL: Record<ApprovalKind, string> = {
  scenario_review: "Scenario review",
  finalization: "Finalisation",
  reopen_request: "Reopen request",
  adjustment: "Adjustment",
};

const KIND_LINK: Record<ApprovalKind, (id: string) => string> = {
  scenario_review: (id) => `/simulator/${id}`,
  finalization: (id) => `/simulator/${id}`,
  reopen_request: (id) => `/simulator/${id}`,
  adjustment: () => "/adjustments",
};

// What the review packet can contain. The engine sends different parts for different kinds, so everything is optional.
interface Packet {
  scenario?: { title?: string; description?: string; version?: number; status?: string };
  adjustment?: { description?: string; reason?: string; entry_date?: string; status?: string };
  headline?: { net_profit_before?: string; net_profit_after?: string; net_profit_change?: string; nodes_changed?: number; overrides_count?: number };
  reopen?: { reason?: string; if_approved?: string };
  reconciliation?: { counts?: Record<string, number>; results?: ReconResult[] };
  lines?: Array<{ code: string; name: string; debit: string; credit: string }>;
  totals?: { debit: string; credit: string; balanced: boolean };
  period_exceptions?: { open: number; open_high_priority: number };
  other_open_scenarios?: Array<{ title?: string; status?: string }>;
  linked_adjustments?: Array<{ description?: string; status?: string }>;
  linked_scenarios?: Array<{ title?: string; status?: string }>;
  decisions?: Record<string, { allowed: boolean; reasons: string[] }>;
  can_decide?: boolean;
  people?: People;
}

function ReviewDialog({
  companyId,
  item,
  onClose,
  onDecided,
}: {
  companyId: string;
  item: ApprovalItem | null;
  onClose: () => void;
  onDecided: () => void;
}) {
  const packet = useApi<Packet>(item ? `companies/${companyId}/approvals/${item.kind}/${item.id}` : null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState<"approve" | "reject" | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function decide(decision: "approve" | "reject") {
    if (!item) return;
    setBusy(decision);
    setError(null);
    try {
      await api(`companies/${companyId}/approvals/${item.kind}/${item.id}/decide`, { method: "POST", body: { decision, note: note.trim() || undefined } });
      setNote("");
      onDecided();
      onClose();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  const p = packet.data;
  const decisions = p?.decisions ?? item?.decisions ?? {};
  const approve = decisions.approve;
  const reject = decisions.reject;
  const rejectOffered = item ? item.kind !== "finalization" : false;
  const reasons = [...(approve && !approve.allowed ? approve.reasons : []), ...(reject && !reject.allowed && rejectOffered ? reject.reasons : [])];

  return (
    <Modal open={item !== null} onClose={onClose} wide title={item ? `${KIND_LABEL[item.kind]}: ${item.title}` : "Review"}>
      {packet.loading && !p ? <Loading /> : null}
      {packet.error ? <Notice kind="error">{packet.error}</Notice> : null}
      {item && p ? (
        <div className="space-y-5">
          {p.reopen ? (
            <div className="space-y-1 text-sm">
              <p>
                Reason for reopening: <strong>{p.reopen.reason}</strong>
              </p>
              {p.reopen.if_approved ? <p className="text-ink-soft">If approved: {p.reopen.if_approved}</p> : null}
            </div>
          ) : null}
          {p.adjustment ? (
            <div className="space-y-1 text-sm">
              <p>
                <strong>{p.adjustment.description}</strong> - entry date {formatDate(p.adjustment.entry_date)}
              </p>
              <p className="text-ink-soft">Reason: {p.adjustment.reason}</p>
            </div>
          ) : null}
          {p.headline ? (
            <div className="grid gap-3 sm:grid-cols-3">
              <Stat label="Net profit now" value={<Money value={p.headline.net_profit_before} />} />
              <Stat label="Net profit after" value={<Money value={p.headline.net_profit_after} />} />
              <Stat label="Change" value={<Money value={p.headline.net_profit_change} />} sub={`${p.headline.nodes_changed ?? 0} figures change`} />
            </div>
          ) : null}
          {p.lines && p.lines.length > 0 ? (
            <TableWrap>
              <Table>
                <thead>
                  <tr>
                    <Th>Account</Th>
                    <Th align="right">Debit</Th>
                    <Th align="right">Credit</Th>
                  </tr>
                </thead>
                <tbody>
                  {p.lines.map((l, i) => (
                    <tr key={i}>
                      <Td>
                        <span className="num text-ink-soft">{l.code}</span> {l.name}
                      </Td>
                      <Td align="right">
                        <Money value={l.debit} />
                      </Td>
                      <Td align="right">
                        <Money value={l.credit} />
                      </Td>
                    </tr>
                  ))}
                  {p.totals ? (
                    <tr className="bg-paper/60 font-semibold">
                      <Td>Total {p.totals.balanced ? <Badge tone="pass">Balanced</Badge> : <Badge tone="fail">Not balanced</Badge>}</Td>
                      <Td align="right">
                        <Money value={p.totals.debit} />
                      </Td>
                      <Td align="right">
                        <Money value={p.totals.credit} />
                      </Td>
                    </tr>
                  ) : null}
                </tbody>
              </Table>
            </TableWrap>
          ) : null}
          {p.period_exceptions ? (
            <p className="text-sm">
              Open exceptions in this period: <strong>{p.period_exceptions.open}</strong>
              {p.period_exceptions.open_high_priority > 0 ? <span className="text-fail"> ({p.period_exceptions.open_high_priority} high priority)</span> : null}
            </p>
          ) : null}
          {p.other_open_scenarios && p.other_open_scenarios.length > 0 ? (
            <Notice kind="warning">Other scenarios are still open in this period: {p.other_open_scenarios.map((s) => `${s.title} (${humanise(s.status)})`).join(", ")}.</Notice>
          ) : null}
          {p.reconciliation?.results && p.reconciliation.results.length > 0 ? (
            <div>
              <h3 className="mb-1 text-sm font-semibold">Checks</h3>
              <ul className="divide-y divide-rule/70 rounded-md border border-rule">
                {p.reconciliation.results.map((r) => (
                  <li key={r.rule_id} className="flex flex-wrap items-start gap-3 px-3 py-2 text-sm">
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
            </div>
          ) : null}
          {[...(p.linked_adjustments ?? []), ...(p.linked_scenarios ?? [])].length > 0 ? (
            <p className="text-sm text-ink-soft">
              Linked: {[...(p.linked_adjustments ?? []).map((a) => `${a.description} (${humanise(a.status)})`), ...(p.linked_scenarios ?? []).map((s) => `${s.title} (${humanise(s.status)})`)].join(", ")}
            </p>
          ) : null}

          {item.decisions && Object.keys(item.decisions).length > 0 && (approve?.allowed || (reject?.allowed && rejectOffered)) ? (
            <div className="space-y-3 border-t border-rule pt-4">
              <Field label="Note" htmlFor="decide-note" hint="Required when rejecting.">
                <Textarea id="decide-note" value={note} onChange={(e) => setNote(e.target.value)} />
              </Field>
              {error ? <Notice kind="error">{error}</Notice> : null}
              <div className="flex flex-wrap gap-2">
                {approve?.allowed ? (
                  <Button loading={busy === "approve"} disabled={busy !== null} onClick={() => void decide("approve")}>
                    Approve
                  </Button>
                ) : null}
                {reject?.allowed && rejectOffered ? (
                  <Button variant="danger" loading={busy === "reject"} disabled={busy !== null || !note.trim()} onClick={() => void decide("reject")}>
                    Reject
                  </Button>
                ) : null}
              </div>
            </div>
          ) : (
            <div className="space-y-2 border-t border-rule pt-4">
              {error ? <Notice kind="error">{error}</Notice> : null}
              <Notice kind="info">
                You cannot decide this one right now.
                {reasons.length > 0 ? ` ${reasons.join(" ")}` : ""}
              </Notice>
            </div>
          )}
        </div>
      ) : null}
    </Modal>
  );
}

function Inbox({ companyId, period, onChanged }: { companyId: string; period: Period; onChanged: () => void }) {
  const [scope, setScope] = useState("all");
  const [kind, setKind] = useState("");
  const [allPeriods, setAllPeriods] = useState(false);
  const { data, error, loading, reload } = useApi<ApprovalInbox>(`companies/${companyId}/approvals/inbox`, {
    periodId: allPeriods ? undefined : period.id,
    scope: scope === "all" ? undefined : scope,
    kind,
  });
  const [open, setOpen] = useState<ApprovalItem | null>(null);

  return (
    <Card>
      <CardHeader title="Waiting for a decision" description="Oldest first. Open one to see what exactly is being approved and what backs it." />
      <div className="flex flex-wrap items-end gap-3 border-b border-rule px-5 py-3">
        <Field label="Show" htmlFor="ap-scope">
          <Select id="ap-scope" value={scope} onChange={(e) => setScope(e.target.value)} className="h-9 w-52">
            <option value="all">Everything waiting</option>
            <option value="mine">Waiting for me to decide</option>
            <option value="waiting">Things I made, waiting on others</option>
          </Select>
        </Field>
        <Field label="Kind" htmlFor="ap-kind">
          <Select id="ap-kind" value={kind} onChange={(e) => setKind(e.target.value)} className="h-9 w-48">
            <option value="">Any</option>
            {(Object.keys(KIND_LABEL) as ApprovalKind[]).map((k) => (
              <option key={k} value={k}>
                {KIND_LABEL[k]}
              </option>
            ))}
          </Select>
        </Field>
        <label className="flex h-9 items-center gap-2 text-sm">
          <input type="checkbox" className="h-4 w-4 accent-[#1f5c47]" checked={allPeriods} onChange={(e) => setAllPeriods(e.target.checked)} />
          All periods
        </label>
      </div>
      {error ? (
        <CardBody>
          <Notice kind="error">{error}</Notice>
        </CardBody>
      ) : null}
      {loading && !data ? <Loading /> : null}
      {data && data.items.length === 0 ? <Empty title="Nothing waiting">No decisions are waiting with these filters.</Empty> : null}
      {data && data.items.length > 0 ? (
        <TableWrap>
          <Table>
            <thead>
              <tr>
                <Th>What</Th>
                <Th>Period</Th>
                <Th>Made by</Th>
                <Th align="right">Waiting</Th>
                <Th>For you</Th>
                <Th />
              </tr>
            </thead>
            <tbody>
              {data.items.map((it) => (
                <tr key={`${it.kind}:${it.id}`}>
                  <Td>
                    <Badge tone="info">{KIND_LABEL[it.kind]}</Badge>
                    <div className="mt-1 font-medium">{it.title}</div>
                    {it.note ? <div className="max-w-md text-xs text-ink-soft">{it.note}</div> : null}
                  </Td>
                  <Td>
                    {it.period_label}
                    {it.period_locked ? <Badge tone="ledger" className="ml-2">Locked</Badge> : null}
                  </Td>
                  <Td>
                    <Who id={it.made_by} people={data.people} />
                  </Td>
                  <Td align="right">{it.waiting_days < 1 ? "today" : `${Math.floor(it.waiting_days)} d`}</Td>
                  <Td>
                    {it.can_decide ? <Badge tone="pass">You can decide</Badge> : it.is_mine ? <Badge>You made it</Badge> : <Badge tone="neutral">Not you</Badge>}
                  </Td>
                  <Td align="right">
                    <Button size="sm" variant={it.can_decide ? "primary" : "secondary"} onClick={() => setOpen(it)}>
                      {it.can_decide ? "Review" : "View"}
                    </Button>
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </TableWrap>
      ) : null}
      <ReviewDialog
        companyId={companyId}
        item={open}
        onClose={() => setOpen(null)}
        onDecided={() => {
          reload();
          onChanged();
        }}
      />
    </Card>
  );
}

function History({ companyId, period }: { companyId: string; period: Period }) {
  const [outcome, setOutcome] = useState("");
  const [allPeriods, setAllPeriods] = useState(false);
  const { data, error, loading } = useApi<ApprovalHistory>(`companies/${companyId}/approvals/history`, {
    periodId: allPeriods ? undefined : period.id,
    outcome,
    limit: 100,
  });
  return (
    <Card>
      <CardHeader title="Decisions taken" description="Newest first. Nothing here can be changed." />
      <div className="flex flex-wrap items-end gap-3 border-b border-rule px-5 py-3">
        <Field label="Outcome" htmlFor="h-outcome">
          <Select id="h-outcome" value={outcome} onChange={(e) => setOutcome(e.target.value)} className="h-9 w-44">
            <option value="">Any</option>
            <option value="APPROVED">Approved</option>
            <option value="REJECTED">Rejected</option>
            <option value="FINALIZED">Finalised</option>
          </Select>
        </Field>
        <label className="flex h-9 items-center gap-2 text-sm">
          <input type="checkbox" className="h-4 w-4 accent-[#1f5c47]" checked={allPeriods} onChange={(e) => setAllPeriods(e.target.checked)} />
          All periods
        </label>
      </div>
      {error ? (
        <CardBody>
          <Notice kind="error">{error}</Notice>
        </CardBody>
      ) : null}
      {loading && !data ? <Loading /> : null}
      {data && data.decisions.length === 0 ? <Empty title="No decisions yet" /> : null}
      {data && data.decisions.length > 0 ? (
        <TableWrap>
          <Table>
            <thead>
              <tr>
                <Th>When</Th>
                <Th>What</Th>
                <Th>Outcome</Th>
                <Th>Decided by</Th>
                <Th>Made by</Th>
                <Th>Note</Th>
              </tr>
            </thead>
            <tbody>
              {data.decisions.map((d, i) => (
                <tr key={`${d.object_id}:${i}`}>
                  <Td className="whitespace-nowrap text-ink-soft">{formatDateTime(d.at)}</Td>
                  <Td>
                    <Badge tone="info">{KIND_LABEL[d.kind]}</Badge>
                    <div className="mt-1">
                      <Link href={KIND_LINK[d.kind](d.object_id)} className="font-medium text-ledger-dark underline decoration-ledger/30 underline-offset-2 hover:decoration-ledger">
                        {d.title}
                      </Link>
                    </div>
                  </Td>
                  <Td>
                    <StatusBadge status={d.outcome} />
                  </Td>
                  <Td>
                    <Who id={d.decided_by} people={data.people} />
                  </Td>
                  <Td>
                    <Who id={d.made_by} people={data.people} />
                  </Td>
                  <Td className="max-w-xs text-ink-soft">{d.note ?? "-"}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </TableWrap>
      ) : null}
    </Card>
  );
}

function Approvals({ companyId, period }: { companyId: string; period: Period }) {
  const [tab, setTab] = useState<"inbox" | "history">("inbox");
  const summary = useApi<ApprovalSummary>(`companies/${companyId}/approvals/summary`, { periodId: period.id });
  const s = summary.data;
  return (
    <div className="space-y-6">
      {summary.error ? <Notice kind="error">{summary.error}</Notice> : null}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Waiting in all" value={s ? s.waiting_total : "-"} sub={s && s.oldest_waiting_days > 0 ? `oldest ${Math.floor(s.oldest_waiting_days)} days` : undefined} />
        <Stat label="Waiting for you" value={s ? s.waiting_for_you : "-"} tone={s && s.waiting_for_you > 0 ? "warn" : undefined} />
        <Stat label="Waiting on others" value={s ? s.waiting_on_others : "-"} />
        <Stat label="Decided so far" value={s ? Object.values(s.decided.total_by_outcome).reduce((a, b) => a + b, 0) : "-"} sub={s ? `${s.decided.total_by_outcome.APPROVED ?? 0} approved, ${s.decided.total_by_outcome.REJECTED ?? 0} rejected` : undefined} />
      </div>
      <Tabs
        tabs={[
          { id: "inbox" as const, label: "Waiting", count: s?.waiting_total },
          { id: "history" as const, label: "History" },
        ]}
        value={tab}
        onChange={setTab}
      />
      {tab === "inbox" ? <Inbox companyId={companyId} period={period} onChanged={summary.reload} /> : <History companyId={companyId} period={period} />}
    </div>
  );
}

export default function ApprovalsPage() {
  return (
    <>
      <PageHeader
        title="Approvals"
        description="Everything waiting for a second pair of eyes: scenario reviews, finalisation, reopen requests and adjustments. Who may decide what, and why not, is shown on each item."
      />
      <Gate needsPeriod>{({ company, period }) => (period ? <Approvals key={`${company.id}:${period.id}`} companyId={company.id} period={period} /> : null)}</Gate>
    </>
  );
}
