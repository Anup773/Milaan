"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
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
import { Money } from "@/components/common/money";
import { api, errorMessage } from "@/lib/api-client";
import { useApi } from "@/lib/use-api";
import { CAN, can, type Role } from "@/lib/roles";
import { formatDate, formatDateTime, humanise, shortId } from "@/lib/format";
import type { Adjustment, ExceptionDetail } from "@/lib/types";

// The review actions the engine's state machine can offer, with the route each one posts to and whether it needs a written reason
// (these mirror engine/exceptions/state_machine.py NEEDS_NOTE and api/src/modules/exceptions/routes.ts).
const ACTIONS: Record<string, { label: string; route: string; needsNote: boolean; help: string; danger?: boolean }> = {
  claim: { label: "Start review", route: "claim", needsNote: false, help: "Take this flag up for review." },
  request_evidence: { label: "Request evidence", route: "request-evidence", needsNote: true, help: "Ask for the document that would explain the entry. Say what is needed." },
  evidence_received: { label: "Evidence received", route: "evidence-received", needsNote: true, help: "Record that the evidence has arrived and what it showed." },
  retain: { label: "Retain as is", route: "retain", needsNote: true, help: "Decide the entry is right. Explain why." },
  correct: { label: "Correct it", route: "correct", needsNote: true, help: "Decide the entry needs correcting. A correction reaches the ledger only through an approved adjustment." },
  reverse: { label: "Reverse it", route: "reverse", needsNote: true, help: "Decide the entry must be reversed. The reversal reaches the ledger only through an approved adjustment.", danger: true },
  resolve: { label: "Mark resolved", route: "resolve", needsNote: false, help: "Close this flag once the adjustment has been posted." },
  reopen: { label: "Reopen", route: "reopen", needsNote: true, help: "Put it back under review. Say why." },
};

const ACTION_ORDER = ["claim", "evidence_received", "retain", "correct", "reverse", "request_evidence", "resolve", "reopen"];

function ActionDialog({
  companyId,
  exceptionId,
  action,
  onClose,
  onDone,
}: {
  companyId: string;
  exceptionId: string;
  action: string | null;
  onClose: () => void;
  onDone: () => void;
}) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const def = action ? ACTIONS[action] : null;

  async function submit() {
    if (!def) return;
    setBusy(true);
    setError(null);
    try {
      await api(`companies/${companyId}/exceptions/${exceptionId}/${def.route}`, {
        method: "POST",
        body: note.trim() ? { note: note.trim() } : {},
      });
      setNote("");
      onDone();
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
          <Button variant={def?.danger ? "danger" : "primary"} loading={busy} disabled={def?.needsNote && !note.trim()} onClick={() => void submit()}>
            {def?.label}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <p className="text-sm text-ink-soft">{def?.help}</p>
        <Field label={def?.needsNote ? "Note (required)" : "Note (optional)"} htmlFor="action-note">
          <Textarea id="action-note" value={note} onChange={(e) => setNote(e.target.value)} />
        </Field>
        {error ? <Notice kind="error">{error}</Notice> : null}
      </div>
    </Modal>
  );
}

function Detail({ companyId, exceptionId, role }: { companyId: string; exceptionId: string; role: Role }) {
  const { data: ex, error, loading, reload } = useApi<ExceptionDetail>(`companies/${companyId}/exceptions/${exceptionId}`);
  const adjustments = useApi<{ adjustments: Adjustment[] }>(`companies/${companyId}/adjustments`);
  const [action, setAction] = useState<string | null>(null);
  const [message, setMessage] = useState<{ kind: "success" | "error"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [linkId, setLinkId] = useState("");

  if (loading && !ex) return <Loading />;
  if (error) return <Notice kind="error">{error}</Notice>;
  if (!ex) return null;

  const reviewer = can(role, CAN.reviewException);
  const maker = can(role, CAN.proposeReversal);
  const offered = ACTION_ORDER.filter((a) => ex.available_actions.includes(a));
  const locked = ex.period_lock_status === "LOCKED";
  const canProposeReversal = ex.decision === "REVERSE" && ex.status === "CORRECTION_PENDING" && ex.linked_adjustments.length === 0;
  const canLink = ex.status === "CORRECTION_PENDING";

  async function run(path: string, body: Record<string, unknown>, success: string) {
    setBusy(true);
    setMessage(null);
    try {
      await api(`companies/${companyId}/exceptions/${exceptionId}/${path}`, { method: "POST", body });
      setMessage({ kind: "success", text: success });
      reload();
      adjustments.reload();
    } catch (err) {
      setMessage({ kind: "error", text: errorMessage(err) });
    } finally {
      setBusy(false);
    }
  }

  const linkable = (adjustments.data?.adjustments ?? []).filter((a) => a.accounting_period_id === ex.accounting_period_id);

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader
          title={ex.title}
          description={`${humanise(ex.category)} - ${ex.source === "MANUAL" ? "raised by a person" : "found by detection"}`}
          actions={
            <>
              <StatusBadge status={ex.priority} />
              <StatusBadge status={ex.status} />
            </>
          }
        />
        <CardBody className="space-y-3">
          <p className="text-sm text-ink">{ex.message}</p>
          <div className="flex flex-wrap gap-x-8 gap-y-1 text-sm text-ink-soft">
            <span>
              Amount: <Money value={ex.amount} className="font-medium text-ink" />
            </span>
            <span>Raised {formatDateTime(ex.created_at)}</span>
            {ex.decision ? <span>Decision: {humanise(ex.decision)}</span> : null}
            {locked ? <Badge tone="ledger">Period locked</Badge> : null}
          </div>
          {ex.decision_note ? <Notice kind="info">Reviewer&rsquo;s note: {ex.decision_note}</Notice> : null}
          {locked ? <Notice kind="warning">This period is locked. Retaining, asking for evidence and closing paperwork still work, but correcting or reversing needs the period reopened first.</Notice> : null}
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="What to do" description={reviewer ? "Only the steps the review process allows from here are shown" : undefined} />
        <CardBody className="space-y-4">
          {!reviewer ? <Notice kind="info">Deciding a flag needs a senior accountant, CA, reviewer or admin. You can still read everything here.</Notice> : null}
          {reviewer && offered.length === 0 ? <p className="text-sm text-ink-soft">Nothing more can be done with this flag.</p> : null}
          {reviewer && offered.length > 0 ? (
            <div className="flex flex-wrap gap-2">
              {offered.map((a) => (
                <Button key={a} variant={a === "claim" ? "primary" : ACTIONS[a].danger ? "danger" : "secondary"} onClick={() => setAction(a)} disabled={busy}>
                  {ACTIONS[a].label}
                </Button>
              ))}
            </div>
          ) : null}
          {reviewer ? <p className="text-xs text-ink-faint">Whoever raised a flag by hand cannot also decide it; the system refuses that and says so.</p> : null}

          {canProposeReversal && maker && !locked ? (
            <div className="rounded-md border border-rule bg-paper/60 p-3">
              <p className="mb-2 text-sm text-ink">This flag was decided REVERSE. Build the mirror-image entry and propose it as an adjustment; a second person must approve it before anything is posted.</p>
              <Button size="sm" loading={busy} onClick={() => void run("propose-reversal", {}, "Reversal proposed as an adjustment. It now waits for approval.")}>
                Propose the reversal
              </Button>
            </div>
          ) : null}

          {canLink && reviewer ? (
            <div className="rounded-md border border-rule bg-paper/60 p-3">
              <p className="mb-2 text-sm text-ink">Tie an adjustment from this period to the flag so the correction is on record.</p>
              <div className="flex flex-wrap items-end gap-2">
                <Field label="Adjustment" htmlFor="link-adj" className="min-w-[18rem] flex-1">
                  <Select id="link-adj" value={linkId} onChange={(e) => setLinkId(e.target.value)}>
                    <option value="">Choose...</option>
                    {linkable.map((a) => (
                      <option key={a.id} value={a.id}>
                        {formatDate(a.entry_date)} - {a.description} ({humanise(a.status)})
                      </option>
                    ))}
                  </Select>
                </Field>
                <Button size="sm" variant="secondary" disabled={!linkId || busy} onClick={() => void run("adjustments", { adjustmentId: linkId }, "Adjustment linked to this flag.")}>
                  Link adjustment
                </Button>
              </div>
            </div>
          ) : null}
          {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="The entry" description="What the flag is about" />
        {ex.entries.length === 0 ? (
          <CardBody>
            <p className="text-sm text-ink-soft">No entry is attached.</p>
          </CardBody>
        ) : (
          ex.entries.map((entry) => (
            <div key={entry.journal_entry_id} className="border-b border-rule last:border-0">
              <div className="flex flex-wrap items-center gap-3 bg-paper/60 px-5 py-2 text-sm">
                <span className="font-medium">{formatDate(entry.entry_date)}</span>
                <span className="text-ink-soft">{entry.description || "(no description)"}</span>
                <span className="num text-xs text-ink-faint">{shortId(entry.journal_entry_id)}</span>
              </div>
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
                    {entry.lines.map((l, i) => (
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
                  </tbody>
                </Table>
              </TableWrap>
            </div>
          ))
        )}
      </Card>

      <Card>
        <CardHeader title="History" description="Every step, oldest first" />
        <ol className="divide-y divide-rule/70">
          {ex.transitions.map((t, i) => (
            <li key={i} className="flex flex-wrap items-start gap-3 px-5 py-3 text-sm">
              <span className="w-40 shrink-0 text-ink-soft">{formatDateTime(t.at)}</span>
              <span className="font-medium">{humanise(t.action)}</span>
              <span className="text-ink-soft">
                {t.from_status ? `${humanise(t.from_status)} to ` : ""}
                {humanise(t.to_status)}
              </span>
              {t.note ? <span className="basis-full pl-[10.75rem] text-ink">&ldquo;{t.note}&rdquo;</span> : null}
            </li>
          ))}
        </ol>
      </Card>

      {ex.linked_adjustments.length > 0 ? (
        <Card>
          <CardHeader title="Linked adjustments" actions={<Link href="/adjustments" className="text-sm font-medium text-ledger">Open adjustments</Link>} />
          <CardBody>
            <ul className="space-y-1 text-sm">
              {ex.linked_adjustments.map((a, i) => (
                <li key={i}>
                  {String((a as Record<string, unknown>).description ?? (a as Record<string, unknown>).adjustment_id ?? "Adjustment")} -{" "}
                  <StatusBadge status={String((a as Record<string, unknown>).status ?? "")} />
                </li>
              ))}
            </ul>
          </CardBody>
        </Card>
      ) : null}

      <ActionDialog companyId={companyId} exceptionId={exceptionId} action={action} onClose={() => setAction(null)} onDone={reload} />
    </div>
  );
}

export default function ExceptionDetailPage() {
  const params = useParams<{ id: string }>();
  return (
    <>
      <PageHeader title="Exception" description="One flag, with its entry, its history and the steps open to you." actions={<Link href="/exceptions" className="text-sm font-medium text-ledger">All exceptions</Link>} />
      <Gate>{({ company, role }) => <Detail key={`${company.id}:${params.id}`} companyId={company.id} exceptionId={params.id} role={role} />}</Gate>
    </>
  );
}