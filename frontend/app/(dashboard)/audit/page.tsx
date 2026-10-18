"use client";

import { useState } from "react";
import { PageHeader } from "@/components/common/page-header";
import { Gate } from "@/components/common/gate";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Field, Input, Select } from "@/components/ui/form";
import { Modal } from "@/components/ui/modal";
import { Table, TableWrap, Td, Th } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Empty, Loading, Notice } from "@/components/common/notice";
import { Stat } from "@/components/common/stat";
import { apiDownload, api, errorMessage, saveBlob, type Query } from "@/lib/api-client";
import { useApi } from "@/lib/use-api";
import { CAN, can, type Role } from "@/lib/roles";
import { formatDateTime } from "@/lib/format";
import type { AuditCatalog, AuditEvent, AuditEventDetail, AuditList, AuditSummary, AuditVerify, Period } from "@/lib/types";

const PAGE_SIZE = 50;

interface Filters {
  action: string;
  objectType: string;
  from: string;
  to: string;
  search: string;
  thisPeriodOnly: boolean;
}

const NO_FILTERS: Filters = { action: "", objectType: "", from: "", to: "", search: "", thisPeriodOnly: false };

function show(value: unknown): string {
  if (value === null || value === undefined) return "-";
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

function EventDialog({ companyId, eventId, onClose, onOpen }: { companyId: string; eventId: string | null; onClose: () => void; onOpen: (id: string) => void }) {
  const { data, error, loading } = useApi<AuditEventDetail>(eventId ? `companies/${companyId}/audit-events/${eventId}` : null);
  return (
    <Modal open={eventId !== null} onClose={onClose} wide title={data ? `Event #${data.seq}` : "Audit event"}>
      {loading && !data ? <Loading /> : null}
      {error ? <Notice kind="error">{error}</Notice> : null}
      {data ? (
        <div className="space-y-5">
          <div>
            <p className="text-sm font-medium text-ink">{data.headline}</p>
            <p className="mt-1 text-sm text-ink-soft">
              {formatDateTime(data.occurred_at)} by {data.actor?.email ?? "the system"}
              {data.actor ? ` (${data.actor.role})` : ""}
            </p>
          </div>
          {data.reason ? (
            <p className="text-sm">
              Reason given: <strong>{data.reason}</strong>
            </p>
          ) : null}
          {data.changes.length > 0 ? (
            <TableWrap>
              <Table>
                <thead>
                  <tr>
                    <Th>Field</Th>
                    <Th>Before</Th>
                    <Th>After</Th>
                  </tr>
                </thead>
                <tbody>
                  {data.changes.map((c) => (
                    <tr key={c.field}>
                      <Td className="font-medium">{c.field}</Td>
                      <Td className="break-all text-ink-soft">{show(c.old)}</Td>
                      <Td className="break-all">{show(c.new)}</Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            </TableWrap>
          ) : (
            <p className="text-sm text-ink-soft">No field-level changes were recorded for this event.</p>
          )}
          <details className="rounded-md border border-rule bg-paper/50 px-3 py-2 text-xs">
            <summary className="cursor-pointer font-medium text-ink-soft">Tamper-evidence (hash chain)</summary>
            <dl className="mt-2 space-y-1 break-all font-mono text-[11px] text-ink-soft">
              <div>
                <dt className="inline font-semibold">This event: </dt>
                <dd className="inline">{data.event_hash}</dd>
              </div>
              <div>
                <dt className="inline font-semibold">Previous event: </dt>
                <dd className="inline">{data.prev_hash}</dd>
              </div>
            </dl>
          </details>
          <div className="flex justify-between gap-2 border-t border-rule pt-3">
            <Button variant="secondary" size="sm" disabled={!data.previous} onClick={() => data.previous && onOpen(data.previous.id)}>
              {data.previous ? `Earlier: #${data.previous.seq}` : "Earlier"}
            </Button>
            <Button variant="secondary" size="sm" disabled={!data.next} onClick={() => data.next && onOpen(data.next.id)}>
              {data.next ? `Later: #${data.next.seq}` : "Later"}
            </Button>
          </div>
        </div>
      ) : null}
    </Modal>
  );
}

function VerifyCard({ companyId }: { companyId: string }) {
  const [result, setResult] = useState<AuditVerify | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    setBusy(true);
    setError(null);
    try {
      setResult(await api<AuditVerify>(`companies/${companyId}/audit-events/verify`));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader title="Check the trail is intact" description="Re-computes every link of the hash chain. Any edited, removed or inserted record breaks it." />
      <CardBody className="space-y-3">
        <Button onClick={() => void run()} loading={busy}>
          Verify now
        </Button>
        {error ? <Notice kind="error">{error}</Notice> : null}
        {result ? (
          result.ok ? (
            <Notice kind="success">
              Intact. {result.events_checked} events checked, latest is #{result.head_seq}.
              {result.head_hash ? <span className="mt-1 block break-all font-mono text-[11px]">Head: {result.head_hash}</span> : null}
            </Notice>
          ) : (
            <Notice kind="error">
              The trail is broken{result.first_broken_seq !== null ? ` at event #${result.first_broken_seq}` : ""}. {result.problem}
            </Notice>
          )
        ) : null}
      </CardBody>
    </Card>
  );
}

function Audit({ companyId, period, role }: { companyId: string; period: Period; role: Role }) {
  const catalog = useApi<AuditCatalog>(`companies/${companyId}/audit-events/catalog`);
  const summary = useApi<AuditSummary>(`companies/${companyId}/audit-events/summary`);
  const [draft, setDraft] = useState<Filters>(NO_FILTERS);
  const [filters, setFilters] = useState<Filters>(NO_FILTERS);
  const [offset, setOffset] = useState(0);
  const [openId, setOpenId] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const [exportNote, setExportNote] = useState<string | null>(null);

  const query: Query = {
    periodId: filters.thisPeriodOnly ? period.id : undefined,
    action: filters.action,
    objectType: filters.objectType,
    from: filters.from,
    to: filters.to,
    search: filters.search.trim(),
    limit: PAGE_SIZE,
    offset,
  };
  const list = useApi<AuditList>(`companies/${companyId}/audit-events`, query);

  function apply() {
    setFilters(draft);
    setOffset(0);
  }
  function clear() {
    setDraft(NO_FILTERS);
    setFilters(NO_FILTERS);
    setOffset(0);
  }

  async function exportCsv() {
    setExporting(true);
    setExportError(null);
    setExportNote(null);
    try {
      const file = await apiDownload(`companies/${companyId}/audit-events/export`, { ...query, limit: undefined, offset: undefined });
      saveBlob(file);
      const rows = file.headers.get("x-audit-rows");
      const truncated = file.headers.get("x-audit-truncated") === "true";
      setExportNote(`${rows ?? "Some"} rows saved${truncated ? ". The export hit its size limit, so narrow the filters to get the rest." : "."}`);
    } catch (err) {
      setExportError(errorMessage(err));
    } finally {
      setExporting(false);
    }
  }

  const data = list.data;
  const s = summary.data;
  const to = data ? Math.min(offset + data.events.length, data.total) : 0;

  return (
    <div className="space-y-6">
      {summary.error ? <Notice kind="error">{summary.error}</Notice> : null}
      <div className="grid gap-3 sm:grid-cols-3">
        <Stat label="Events recorded" value={s ? s.total : "-"} />
        <Stat label="First event" value={s?.first_event_at ? formatDateTime(s.first_event_at) : "-"} />
        <Stat label="Latest event" value={s?.last_event_at ? formatDateTime(s.last_event_at) : "-"} sub={s ? `#${s.latest_seq}` : undefined} />
      </div>

      {can(role, CAN.verifyAudit) ? <VerifyCard companyId={companyId} /> : null}

      <Card>
        <CardHeader title="Everything that happened" description="Every change, who made it and when. Records are append-only." />
        <div className="grid gap-3 border-b border-rule px-5 py-4 sm:grid-cols-2 lg:grid-cols-4">
          <Field label="What happened" htmlFor="au-action">
            <Select id="au-action" value={draft.action} onChange={(e) => setDraft({ ...draft, action: e.target.value })}>
              <option value="">Anything</option>
              {catalog.data?.action_groups.map((g) => (
                <option key={g} value={g}>
                  All {g.replace(/_/g, " ")}
                </option>
              ))}
              {catalog.data?.actions.map((a) => (
                <option key={a.action} value={a.action}>
                  {a.label}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="About" htmlFor="au-type">
            <Select id="au-type" value={draft.objectType} onChange={(e) => setDraft({ ...draft, objectType: e.target.value })}>
              <option value="">Anything</option>
              {catalog.data?.object_types.map((o) => (
                <option key={o.object_type} value={o.object_type}>
                  {o.label}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="From" htmlFor="au-from">
            <Input id="au-from" type="date" value={draft.from} onChange={(e) => setDraft({ ...draft, from: e.target.value })} />
          </Field>
          <Field label="To" htmlFor="au-to">
            <Input id="au-to" type="date" value={draft.to} onChange={(e) => setDraft({ ...draft, to: e.target.value })} />
          </Field>
          <Field label="Search" htmlFor="au-search" className="sm:col-span-2">
            <Input id="au-search" value={draft.search} onChange={(e) => setDraft({ ...draft, search: e.target.value })} placeholder="a reason, an amount, a name" onKeyDown={(e) => e.key === "Enter" && apply()} />
          </Field>
          <label className="flex items-end gap-2 pb-2 text-sm">
            <input type="checkbox" className="h-4 w-4 accent-[#1f5c47]" checked={draft.thisPeriodOnly} onChange={(e) => setDraft({ ...draft, thisPeriodOnly: e.target.checked })} />
            Only {period.label}
          </label>
          <div className="flex items-end gap-2">
            <Button onClick={apply}>Apply</Button>
            <Button variant="secondary" onClick={clear}>
              Clear
            </Button>
          </div>
        </div>
        {can(role, CAN.exportAudit) ? (
          <div className="flex flex-wrap items-center gap-3 border-b border-rule px-5 py-3">
            <Button variant="secondary" size="sm" loading={exporting} onClick={() => void exportCsv()}>
              Download as CSV
            </Button>
            <span className="text-xs text-ink-faint">Uses the filters above, not the page you are on.</span>
            {exportNote ? <span className="text-xs text-pass">{exportNote}</span> : null}
            {exportError ? <span className="text-xs text-fail">{exportError}</span> : null}
          </div>
        ) : null}
        {list.error ? (
          <CardBody>
            <Notice kind="error">{list.error}</Notice>
          </CardBody>
        ) : null}
        {list.loading && !data ? <Loading /> : null}
        {data && data.events.length === 0 ? <Empty title="No events match" /> : null}
        {data && data.events.length > 0 ? (
          <>
            <TableWrap>
              <Table>
                <thead>
                  <tr>
                    <Th align="right">#</Th>
                    <Th>When</Th>
                    <Th>Who</Th>
                    <Th>What happened</Th>
                    <Th>About</Th>
                    <Th />
                  </tr>
                </thead>
                <tbody>
                  {data.events.map((ev: AuditEvent) => (
                    <tr key={ev.id}>
                      <Td align="right" className="text-ink-faint">
                        {ev.seq}
                      </Td>
                      <Td className="whitespace-nowrap text-ink-soft">{formatDateTime(ev.occurred_at)}</Td>
                      <Td>{ev.actor?.email ?? "system"}</Td>
                      <Td>
                        <Badge tone="info">{ev.action_label}</Badge>
                        <div className="mt-1 max-w-md text-xs text-ink-soft">{ev.headline}</div>
                      </Td>
                      <Td>{ev.object_label}</Td>
                      <Td align="right">
                        <Button size="sm" variant="secondary" onClick={() => setOpenId(ev.id)}>
                          Details
                        </Button>
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            </TableWrap>
            <div className="flex items-center justify-between gap-3 px-5 py-3 text-sm text-ink-soft">
              <span>
                {offset + 1}-{to} of {data.total}
              </span>
              <span className="flex gap-2">
                <Button size="sm" variant="secondary" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
                  Newer
                </Button>
                <Button size="sm" variant="secondary" disabled={!data.has_more} onClick={() => setOffset(offset + PAGE_SIZE)}>
                  Older
                </Button>
              </span>
            </div>
          </>
        ) : null}
      </Card>

      <EventDialog companyId={companyId} eventId={openId} onClose={() => setOpenId(null)} onOpen={setOpenId} />
    </div>
  );
}

export default function AuditPage() {
  return (
    <>
      <PageHeader title="Audit trail" description="A permanent, tamper-evident record of every change: what, who, when and why." />
      <Gate needsPeriod>
        {({ company, period, role }) =>
          !can(role, CAN.readAudit) ? (
            <Notice kind="info">The audit trail is open to senior accountants, chartered accountants, reviewers and admins.</Notice>
          ) : period ? (
            <Audit key={`${company.id}:${period.id}`} companyId={company.id} period={period} role={role} />
          ) : null
        }
      </Gate>
    </>
  );
}
