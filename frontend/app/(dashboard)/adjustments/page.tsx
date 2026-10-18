"use client";

import { useMemo, useState, type FormEvent } from "react";
import { PageHeader } from "@/components/common/page-header";
import { Gate } from "@/components/common/gate";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Field, Input, Select, Textarea } from "@/components/ui/form";
import { Modal } from "@/components/ui/modal";
import { Table, TableWrap, Td, Th } from "@/components/ui/table";
import { StatusBadge } from "@/components/common/status";
import { Empty, Loading, Notice } from "@/components/common/notice";
import { Money } from "@/components/common/money";
import { Who } from "@/components/common/who";
import { api, errorMessage } from "@/lib/api-client";
import { useApi } from "@/lib/use-api";
import { CAN, can, type Role } from "@/lib/roles";
import { formatDate, formatDateTime, formatMoney } from "@/lib/format";
import type { Account, Adjustment, AdjustmentDetail, Period } from "@/lib/types";

interface DraftLine {
  key: number;
  accountId: string;
  debit: string;
  credit: string;
}

/** "1,234.5" -> 123450n cents, or null when it is not an amount. Exact: no floats. */
function toCents(raw: string): bigint | null {
  const text = raw.replace(/[,\s]/g, "");
  if (text === "") return 0n;
  if (!/^\d+(\.\d{1,2})?$/.test(text)) return null;
  const [whole, fraction = ""] = text.split(".");
  return BigInt(whole) * 100n + BigInt((fraction + "00").slice(0, 2));
}

function centsToText(cents: bigint): string {
  const negative = cents < 0n;
  const abs = negative ? -cents : cents;
  return `${negative ? "-" : ""}${abs / 100n}.${(abs % 100n).toString().padStart(2, "0")}`;
}

function ProposeDialog({
  companyId,
  period,
  accounts,
  open,
  onClose,
  onDone,
}: {
  companyId: string;
  period: Period;
  accounts: Account[];
  open: boolean;
  onClose: () => void;
  onDone: () => void;
}) {
  const [nextKey, setNextKey] = useState(3);
  const [lines, setLines] = useState<DraftLine[]>([
    { key: 1, accountId: "", debit: "", credit: "" },
    { key: 2, accountId: "", debit: "", credit: "" },
  ]);
  const [entryDate, setEntryDate] = useState(period.period_end);
  const [description, setDescription] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const totals = useMemo(() => {
    let debit = 0n;
    let credit = 0n;
    let valid = true;
    for (const l of lines) {
      const d = toCents(l.debit);
      const c = toCents(l.credit);
      if (d === null || c === null) valid = false;
      else {
        debit += d;
        credit += c;
      }
    }
    return { debit, credit, valid };
  }, [lines]);

  const problem = useMemo(() => {
    if (!totals.valid) return "An amount is not a valid number (use digits and at most two decimals).";
    for (const l of lines) {
      const d = toCents(l.debit) ?? 0n;
      const c = toCents(l.credit) ?? 0n;
      if (!l.accountId) return "Choose an account on every line.";
      if (d > 0n && c > 0n) return "A line is either a debit or a credit, not both.";
      if (d === 0n && c === 0n) return "Every line needs an amount.";
    }
    if (totals.debit !== totals.credit) return `Debits and credits must be equal (difference ${centsToText(totals.debit - totals.credit)}).`;
    if (entryDate < period.period_start || entryDate > period.period_end) return `The date must fall within ${period.label}.`;
    return null;
  }, [lines, totals, entryDate, period]);

  function update(key: number, patch: Partial<DraftLine>) {
    setLines((current) => current.map((l) => (l.key === key ? { ...l, ...patch } : l)));
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (problem) return;
    setBusy(true);
    setError(null);
    try {
      await api(`companies/${companyId}/adjustments`, {
        method: "POST",
        body: {
          periodId: period.id,
          entryDate,
          description: description.trim(),
          reason: reason.trim(),
          lines: lines.map((l) => ({
            accountId: l.accountId,
            debit: centsToText(toCents(l.debit) ?? 0n),
            credit: centsToText(toCents(l.credit) ?? 0n),
          })),
        },
      });
      setDescription("");
      setReason("");
      setLines([
        { key: nextKey, accountId: "", debit: "", credit: "" },
        { key: nextKey + 1, accountId: "", debit: "", credit: "" },
      ]);
      setNextKey(nextKey + 2);
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
      open={open}
      onClose={onClose}
      wide
      title="Propose an adjustment"
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" form="propose-form" loading={busy} disabled={!!problem || !description.trim() || !reason.trim()}>
            Propose adjustment
          </Button>
        </>
      }
    >
      <form id="propose-form" onSubmit={submit} className="space-y-4">
        <p className="text-sm text-ink-soft">
          An adjustment is a journal entry that fixes or adds to the books. It reaches the ledger only after a second person approves it. Whoever proposes it cannot approve it.
        </p>
        <div className="grid gap-3 sm:grid-cols-[10rem_1fr]">
          <Field label="Entry date" htmlFor="adj-date">
            <Input id="adj-date" type="date" value={entryDate} min={period.period_start} max={period.period_end} onChange={(e) => setEntryDate(e.target.value)} />
          </Field>
          <Field label="What is it?" htmlFor="adj-desc">
            <Input id="adj-desc" value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Extra depreciation on the CNC machine" />
          </Field>
        </div>
        <Field label="Why is it needed?" htmlFor="adj-reason">
          <Textarea id="adj-reason" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="The schedule shows more depreciation than was booked." />
        </Field>

        <div className="overflow-x-auto rounded-md border border-rule">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-paper/60 text-left text-xs font-semibold uppercase tracking-wide text-ink-soft">
                <th className="px-3 py-2">Account</th>
                <th className="w-36 px-3 py-2 text-right">Debit</th>
                <th className="w-36 px-3 py-2 text-right">Credit</th>
                <th className="w-10" />
              </tr>
            </thead>
            <tbody>
              {lines.map((l, index) => (
                <tr key={l.key} className="border-t border-rule/70">
                  <td className="px-3 py-2">
                    <Select aria-label={`Account for line ${index + 1}`} value={l.accountId} onChange={(e) => update(l.key, { accountId: e.target.value })} className="h-9">
                      <option value="">Choose an account...</option>
                      {accounts.map((a) => (
                        <option key={a.id} value={a.id}>
                          {a.code} {a.name}
                        </option>
                      ))}
                    </Select>
                  </td>
                  <td className="px-3 py-2">
                    <Input aria-label={`Debit for line ${index + 1}`} inputMode="decimal" value={l.debit} onChange={(e) => update(l.key, { debit: e.target.value })} className="num h-9 text-right" />
                  </td>
                  <td className="px-3 py-2">
                    <Input aria-label={`Credit for line ${index + 1}`} inputMode="decimal" value={l.credit} onChange={(e) => update(l.key, { credit: e.target.value })} className="num h-9 text-right" />
                  </td>
                  <td className="px-1 py-2">
                    {lines.length > 2 ? (
                      <button type="button" aria-label={`Remove line ${index + 1}`} className="rounded p-1 text-ink-faint hover:bg-paper hover:text-fail" onClick={() => setLines((c) => c.filter((x) => x.key !== l.key))}>
                        <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
                          <path d="M3 3l10 10M13 3L3 13" />
                        </svg>
                      </button>
                    ) : null}
                  </td>
                </tr>
              ))}
              <tr className="border-t border-rule bg-paper/60 font-semibold">
                <td className="px-3 py-2">
                  <button
                    type="button"
                    className="text-sm font-medium text-ledger hover:underline"
                    onClick={() => {
                      setLines((c) => [...c, { key: nextKey, accountId: "", debit: "", credit: "" }]);
                      setNextKey(nextKey + 1);
                    }}
                  >
                    + Add a line
                  </button>
                </td>
                <td className="num px-3 py-2 text-right">{formatMoney(centsToText(totals.debit))}</td>
                <td className="num px-3 py-2 text-right">{formatMoney(centsToText(totals.credit))}</td>
                <td />
              </tr>
            </tbody>
          </table>
        </div>
        {problem ? <p className="text-sm text-ink-soft">{problem}</p> : <Notice kind="success">Debits equal credits.</Notice>}
        {error ? <Notice kind="error">{error}</Notice> : null}
      </form>
    </Modal>
  );
}

function DecideDialog({
  companyId,
  adjustment,
  mode,
  onClose,
  onDone,
}: {
  companyId: string;
  adjustment: Adjustment | null;
  mode: "approve" | "reject";
  onClose: () => void;
  onDone: () => void;
}) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    if (!adjustment) return;
    setBusy(true);
    setError(null);
    try {
      await api(`companies/${companyId}/adjustments/${adjustment.id}/${mode}`, { method: "POST", body: mode === "reject" ? { note: note.trim() } : {} });
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
      open={adjustment !== null}
      onClose={onClose}
      title={mode === "approve" ? "Approve and post this adjustment?" : "Reject this adjustment"}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button variant={mode === "approve" ? "primary" : "danger"} loading={busy} disabled={mode === "reject" && !note.trim()} onClick={() => void submit()}>
            {mode === "approve" ? "Approve and post" : "Reject"}
          </Button>
        </>
      }
    >
      {adjustment ? (
        <div className="space-y-4">
          <p className="text-sm text-ink-soft">
            <strong className="text-ink">{adjustment.description}</strong> - {adjustment.reason}
          </p>
          {mode === "approve" ? (
            <p className="text-sm text-ink-soft">Approving posts it to the ledger as a journal entry. The period must be open, and you must not be the person who proposed it.</p>
          ) : (
            <Field label="Why is it rejected? (required)" htmlFor="reject-note">
              <Textarea id="reject-note" value={note} onChange={(e) => setNote(e.target.value)} />
            </Field>
          )}
          {error ? <Notice kind="error">{error}</Notice> : null}
        </div>
      ) : null}
    </Modal>
  );
}

function DetailDialog({ companyId, id, accounts, onClose }: { companyId: string; id: string | null; accounts: Account[]; onClose: () => void }) {
  const { data, error, loading } = useApi<AdjustmentDetail>(id ? `companies/${companyId}/adjustments/${id}` : null);
  const name = (accountId: string) => {
    const a = accounts.find((x) => x.id === accountId);
    return a ? `${a.code} ${a.name}` : accountId.slice(0, 8);
  };
  return (
    <Modal open={id !== null} onClose={onClose} title="Adjustment" wide>
      {loading && !data ? <Loading /> : null}
      {error ? <Notice kind="error">{error}</Notice> : null}
      {data ? (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-3">
            <StatusBadge status={data.status} />
            <span className="text-sm text-ink-soft">Entry date {formatDate(data.entry_date)}</span>
          </div>
          <p className="text-sm text-ink">
            <strong>{data.description}</strong>
          </p>
          <p className="text-sm text-ink-soft">Reason: {data.reason}</p>
          {data.rejection_note ? <Notice kind="error">Rejected: {data.rejection_note}</Notice> : null}
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
                {data.lines.map((l, i) => (
                  <tr key={i}>
                    <Td>{name(l.account_id)}</Td>
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
          <p className="text-xs text-ink-faint">Proposed {formatDateTime(data.created_at)}{data.journal_entry_id ? " - posted to the ledger" : ""}</p>
        </div>
      ) : null}
    </Modal>
  );
}

function Adjustments({ companyId, period, role }: { companyId: string; period: Period; role: Role }) {
  const [status, setStatus] = useState("");
  const list = useApi<{ adjustments: Adjustment[] }>(`companies/${companyId}/adjustments`, { status });
  const accounts = useApi<{ accounts: Account[] }>(`companies/${companyId}/accounts`);
  const [proposing, setProposing] = useState(false);
  const [viewing, setViewing] = useState<string | null>(null);
  const [deciding, setDeciding] = useState<{ adjustment: Adjustment; mode: "approve" | "reject" } | null>(null);

  const inPeriod = (list.data?.adjustments ?? []).filter((a) => a.accounting_period_id === period.id);
  const decider = can(role, CAN.decideAdjustment);
  const proposer = can(role, CAN.proposeAdjustment);

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader
          title={`Adjustments - ${period.label}`}
          description="Proposed by one person, approved by another, then posted to the ledger"
          actions={
            proposer ? (
              period.lock_status === "OPEN" ? (
                <Button size="sm" onClick={() => setProposing(true)}>
                  Propose an adjustment
                </Button>
              ) : (
                <span className="text-sm text-ink-soft">This period is locked</span>
              )
            ) : null
          }
        />
        <div className="flex items-end gap-3 border-b border-rule px-5 py-3">
          <Field label="Status" htmlFor="adj-status">
            <Select id="adj-status" value={status} onChange={(e) => setStatus(e.target.value)} className="h-9 w-48">
              <option value="">Any</option>
              <option value="REVIEW_REQUIRED">Needs review</option>
              <option value="POSTED">Posted</option>
              <option value="REJECTED">Rejected</option>
            </Select>
          </Field>
        </div>
        {list.error ? (
          <CardBody>
            <Notice kind="error">{list.error}</Notice>
          </CardBody>
        ) : null}
        {list.loading && !list.data ? <Loading /> : null}
        {list.data && inPeriod.length === 0 ? <Empty title="No adjustments for this period" /> : null}
        {inPeriod.length > 0 ? (
          <TableWrap>
            <Table>
              <thead>
                <tr>
                  <Th>Date</Th>
                  <Th>Adjustment</Th>
                  <Th>Proposed by</Th>
                  <Th>Status</Th>
                  <Th />
                </tr>
              </thead>
              <tbody>
                {inPeriod.map((a) => (
                  <tr key={a.id}>
                    <Td className="whitespace-nowrap">{formatDate(a.entry_date)}</Td>
                    <Td>
                      <button type="button" onClick={() => setViewing(a.id)} className="text-left font-medium text-ledger-dark underline decoration-ledger/30 underline-offset-2 hover:decoration-ledger">
                        {a.description}
                      </button>
                      <div className="mt-0.5 max-w-md text-xs text-ink-soft">{a.reason}</div>
                    </Td>
                    <Td>
                      <Who id={a.proposed_by} />
                    </Td>
                    <Td>
                      <StatusBadge status={a.status} />
                      {a.rejection_note ? <div className="mt-1 max-w-xs text-xs text-fail">{a.rejection_note}</div> : null}
                    </Td>
                    <Td align="right">
                      {a.status === "REVIEW_REQUIRED" && decider ? (
                        <div className="flex justify-end gap-2">
                          <Button size="sm" onClick={() => setDeciding({ adjustment: a, mode: "approve" })}>
                            Approve
                          </Button>
                          <Button size="sm" variant="secondary" onClick={() => setDeciding({ adjustment: a, mode: "reject" })}>
                            Reject
                          </Button>
                        </div>
                      ) : null}
                      {a.status === "REVIEW_REQUIRED" && !decider ? <span className="text-xs text-ink-faint">Needs a senior accountant, CA or reviewer</span> : null}
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </TableWrap>
        ) : null}
      </Card>

      <ProposeDialog
        key={`${period.id}:${proposing}`}
        companyId={companyId}
        period={period}
        accounts={accounts.data?.accounts ?? []}
        open={proposing}
        onClose={() => setProposing(false)}
        onDone={list.reload}
      />
      <DetailDialog companyId={companyId} id={viewing} accounts={accounts.data?.accounts ?? []} onClose={() => setViewing(null)} />
      <DecideDialog
        companyId={companyId}
        adjustment={deciding?.adjustment ?? null}
        mode={deciding?.mode ?? "approve"}
        onClose={() => setDeciding(null)}
        onDone={list.reload}
      />
    </div>
  );
}

export default function AdjustmentsPage() {
  return (
    <>
      <PageHeader title="Adjustments" description="Corrections to the books. Each is proposed by one person and must be approved by a different one before it is posted." />
      <Gate needsPeriod>{({ company, period, role }) => (period ? <Adjustments key={`${company.id}:${period.id}`} companyId={company.id} period={period} role={role} /> : null)}</Gate>
    </>
  );
}