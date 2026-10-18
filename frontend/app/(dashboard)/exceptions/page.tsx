"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";
import { PageHeader } from "@/components/common/page-header";
import { Gate } from "@/components/common/gate";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Field, Input, Select, Textarea } from "@/components/ui/form";
import { Modal } from "@/components/ui/modal";
import { Table, TableWrap, Td, Th } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { StatusBadge } from "@/components/common/status";
import { Empty, Loading, Notice } from "@/components/common/notice";
import { Money } from "@/components/common/money";
import { api, errorMessage } from "@/lib/api-client";
import { useApi } from "@/lib/use-api";
import { formatDate, formatDateTime, humanise } from "@/lib/format";
import type {
  Account,
  DetectionRun,
  ExceptionListItem,
  ExceptionStatus,
  ExceptionSummary,
  GeneralLedger,
  Period,
} from "@/lib/types";

const STATUSES: ExceptionStatus[] = ["FLAGGED", "UNDER_REVIEW", "EVIDENCE_REQUESTED", "CORRECTION_PENDING", "RETAINED", "RESOLVED", "CLEARED"];
const CATEGORIES = [
  "DUPLICATE_INVOICE",
  "DUPLICATE_AMOUNT",
  "MISSING_EVIDENCE",
  "VENDOR_MISMATCH",
  "UNUSUAL_TRANSACTION",
  "PERIOD_CUTOFF",
  "UNSUPPORTED_EXPENSE",
  "OTHER",
];

function RaiseDialog({
  companyId,
  period,
  open,
  onClose,
  onRaised,
}: {
  companyId: string;
  period: Period;
  open: boolean;
  onClose: () => void;
  onRaised: () => void;
}) {
  const accounts = useApi<{ accounts: Account[] }>(open ? `companies/${companyId}/accounts` : null);
  const [accountId, setAccountId] = useState("");
  const chosenAccount = accountId || accounts.data?.accounts[0]?.id || "";
  const ledger = useApi<GeneralLedger>(open && chosenAccount ? `companies/${companyId}/statements/general-ledger` : null, {
    accountId: chosenAccount,
    periodId: period.id,
  });
  const [entryId, setEntryId] = useState("");
  const [title, setTitle] = useState("");
  const [note, setNote] = useState("");
  const [priority, setPriority] = useState("MEDIUM");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const lines = ledger.data?.lines ?? [];
  const chosenEntry = lines.some((l) => l.journal_entry_id === entryId) ? entryId : (lines[0]?.journal_entry_id ?? "");

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await api(`companies/${companyId}/exceptions`, {
        method: "POST",
        body: { journalEntryId: chosenEntry, note: note.trim(), title: title.trim() || undefined, priority },
      });
      setNote("");
      setTitle("");
      onRaised();
      onClose();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Flag an entry for review"
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" form="raise-form" loading={busy} disabled={!chosenEntry || !note.trim()}>
            Flag entry
          </Button>
        </>
      }
    >
      <form id="raise-form" onSubmit={submit} className="space-y-4">
        <p className="text-sm text-ink-soft">Use this for something the automatic checks would not catch. A reviewer other than you will decide it.</p>
        <Field label="Account" htmlFor="raise-account">
          <Select id="raise-account" value={chosenAccount} onChange={(e) => setAccountId(e.target.value)}>
            {(accounts.data?.accounts ?? []).map((a) => (
              <option key={a.id} value={a.id}>
                {a.code} {a.name}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Entry" htmlFor="raise-entry" hint={ledger.loading ? "Loading entries..." : lines.length === 0 ? "No entries on this account in this period." : undefined}>
          <Select id="raise-entry" value={chosenEntry} onChange={(e) => setEntryId(e.target.value)} disabled={lines.length === 0}>
            {lines.map((l, i) => (
              <option key={`${l.journal_entry_id}-${i}`} value={l.journal_entry_id}>
                {formatDate(l.entry_date)} - {l.description || "(no description)"} - Dr {l.debit} Cr {l.credit}
              </option>
            ))}
          </Select>
        </Field>
        <div className="grid gap-3 sm:grid-cols-[1fr_9rem]">
          <Field label="Short title (optional)" htmlFor="raise-title">
            <Input id="raise-title" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Looks like a personal expense" />
          </Field>
          <Field label="Priority" htmlFor="raise-priority">
            <Select id="raise-priority" value={priority} onChange={(e) => setPriority(e.target.value)}>
              <option value="HIGH">High</option>
              <option value="MEDIUM">Medium</option>
              <option value="LOW">Low</option>
            </Select>
          </Field>
        </div>
        <Field label="Why does it need review?" htmlFor="raise-note">
          <Textarea id="raise-note" value={note} onChange={(e) => setNote(e.target.value)} />
        </Field>
        {error ? <Notice kind="error">{error}</Notice> : null}
      </form>
    </Modal>
  );
}

function Exceptions({ companyId, period }: { companyId: string; period: Period }) {
  const [status, setStatus] = useState("");
  const [category, setCategory] = useState("");
  const [priority, setPriority] = useState("");
  const [openOnly, setOpenOnly] = useState(true);
  const summary = useApi<ExceptionSummary>(`companies/${companyId}/exceptions/summary`, { periodId: period.id });
  const list = useApi<{ exceptions: ExceptionListItem[]; count: number }>(`companies/${companyId}/exceptions`, {
    periodId: period.id,
    status,
    category,
    priority,
    openOnly: openOnly ? "true" : undefined,
  });
  const [detecting, setDetecting] = useState(false);
  const [detection, setDetection] = useState<DetectionRun | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [raising, setRaising] = useState(false);

  async function detect() {
    setDetecting(true);
    setError(null);
    try {
      const result = await api<DetectionRun>(`companies/${companyId}/exceptions/detect`, { method: "POST", body: { periodId: period.id } });
      setDetection(result);
      list.reload();
      summary.reload();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setDetecting(false);
    }
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader
          title="Detection"
          description={
            summary.data?.last_run ? `Last run ${formatDateTime(summary.data.last_run.run_at)}` : "Not run yet for this period"
          }
          actions={
            <>
              <Button variant="secondary" size="sm" onClick={() => setRaising(true)}>
                Flag an entry
              </Button>
              <Button size="sm" loading={detecting} onClick={() => void detect()}>
                Run detection
              </Button>
            </>
          }
        />
        <CardBody className="space-y-3">
          {error ? <Notice kind="error">{error}</Notice> : null}
          {summary.error ? <Notice kind="error">{summary.error}</Notice> : null}
          {summary.data ? (
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <span className="num text-2xl font-semibold text-ink">{summary.data.open_total}</span>
              <span className="text-ink-soft">open</span>
              {(["HIGH", "MEDIUM", "LOW"] as const).map((p) =>
                summary.data!.open_by_priority[p] ? (
                  <Badge key={p} tone={p === "HIGH" ? "fail" : p === "MEDIUM" ? "warn" : "neutral"}>
                    {summary.data!.open_by_priority[p]} {p.toLowerCase()}
                  </Badge>
                ) : null,
              )}
            </div>
          ) : null}
          {detection ? (
            <div className="space-y-2">
              <Notice kind="success">
                Detection finished: {detection.counts.findings} findings, {detection.counts.new} new, {detection.counts.cleared} cleared, {detection.counts.open_after} open now.
              </Notice>
              <ul className="divide-y divide-rule/70 rounded-md border border-rule">
                {detection.rules.map((r) => (
                  <li key={r.rule_id} className="flex flex-wrap items-center gap-3 px-3 py-2 text-sm">
                    <Badge tone={r.status === "CHECKED" ? (r.findings > 0 ? "warn" : "pass") : "neutral"}>{r.status === "CHECKED" ? (r.findings > 0 ? `${r.findings} found` : "Clear") : "Not checked"}</Badge>
                    <span className="font-medium">{r.title}</span>
                    <span className="text-ink-soft">{r.message}</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Flags" description="Open the ones that need a decision" />
        <div className="flex flex-wrap items-end gap-3 border-b border-rule px-5 py-3">
          <Field label="Status" htmlFor="f-status">
            <Select id="f-status" value={status} onChange={(e) => setStatus(e.target.value)} className="h-9 w-44">
              <option value="">Any</option>
              {STATUSES.map((s) => (
                <option key={s} value={s}>
                  {humanise(s)}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Kind" htmlFor="f-category">
            <Select id="f-category" value={category} onChange={(e) => setCategory(e.target.value)} className="h-9 w-52">
              <option value="">Any</option>
              {CATEGORIES.map((c) => (
                <option key={c} value={c}>
                  {humanise(c)}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Priority" htmlFor="f-priority">
            <Select id="f-priority" value={priority} onChange={(e) => setPriority(e.target.value)} className="h-9 w-32">
              <option value="">Any</option>
              <option value="HIGH">High</option>
              <option value="MEDIUM">Medium</option>
              <option value="LOW">Low</option>
            </Select>
          </Field>
          <label className="flex h-9 items-center gap-2 text-sm text-ink">
            <input type="checkbox" checked={openOnly} onChange={(e) => setOpenOnly(e.target.checked)} className="h-4 w-4 accent-[#1f5c47]" />
            Open ones only
          </label>
        </div>
        {list.error ? (
          <CardBody>
            <Notice kind="error">{list.error}</Notice>
          </CardBody>
        ) : null}
        {list.loading && !list.data ? <Loading /> : null}
        {list.data && list.data.exceptions.length === 0 ? <Empty title="Nothing to show">No flags match these filters.</Empty> : null}
        {list.data && list.data.exceptions.length > 0 ? (
          <TableWrap>
            <Table>
              <thead>
                <tr>
                  <Th>Flag</Th>
                  <Th>Kind</Th>
                  <Th>Priority</Th>
                  <Th align="right">Amount</Th>
                  <Th>Status</Th>
                  <Th>Raised</Th>
                </tr>
              </thead>
              <tbody>
                {list.data.exceptions.map((e) => (
                  <tr key={e.id}>
                    <Td>
                      <Link href={`/exceptions/${e.id}`} className="font-medium text-ledger-dark underline decoration-ledger/30 underline-offset-2 hover:decoration-ledger">
                        {e.title}
                      </Link>
                      <div className="mt-0.5 max-w-md text-xs text-ink-soft">{e.message}</div>
                    </Td>
                    <Td>{humanise(e.category)}</Td>
                    <Td>
                      <StatusBadge status={e.priority} />
                    </Td>
                    <Td align="right">
                      <Money value={e.amount} />
                    </Td>
                    <Td>
                      <StatusBadge status={e.status} />
                    </Td>
                    <Td className="whitespace-nowrap text-ink-soft">{formatDateTime(e.created_at)}</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </TableWrap>
        ) : null}
      </Card>

      <RaiseDialog
        companyId={companyId}
        period={period}
        open={raising}
        onClose={() => setRaising(false)}
        onRaised={() => {
          list.reload();
          summary.reload();
        }}
      />
    </div>
  );
}

export default function ExceptionsPage() {
  return (
    <>
      <PageHeader
        title="Exceptions"
        description="Entries that look wrong: duplicates, missing vouchers, odd amounts, entries outside the period. Each one is reviewed, decided and kept on record."
      />
      <Gate needsPeriod>{({ company, period }) => (period ? <Exceptions key={`${company.id}:${period.id}`} companyId={company.id} period={period} /> : null)}</Gate>
    </>
  );
}
