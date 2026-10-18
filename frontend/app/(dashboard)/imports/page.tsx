"use client";

import Link from "next/link";
import { useRef, useState, type FormEvent } from "react";
import { PageHeader } from "@/components/common/page-header";
import { Gate } from "@/components/common/gate";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/form";
import { Table, TableWrap, Td, Th } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { StatusBadge } from "@/components/common/status";
import { Money } from "@/components/common/money";
import { Empty, Loading, Notice } from "@/components/common/notice";
import { Who } from "@/components/common/who";
import { api, apiUpload, errorMessage } from "@/lib/api-client";
import { useApi } from "@/lib/use-api";
import { useWorkspace } from "@/lib/workspace";
import { CAN, can, type Role } from "@/lib/roles";
import { formatDate, formatDateTime } from "@/lib/format";
import type { ImportResult, SourceFile } from "@/lib/types";

const MAX_SHOWN_ISSUES = 25;

function PeriodsCard({ companyId, role }: { companyId: string; role: Role }) {
  const { periods, reloadPeriods, setPeriodId } = useWorkspace();
  const [label, setLabel] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function create(event: FormEvent) {
    event.preventDefault();
    setError(null);
    if (end < start) {
      setError("The period cannot end before it starts.");
      return;
    }
    setBusy(true);
    try {
      const result = await api<{ period: { id: string } }>(`companies/${companyId}/accounting-periods`, {
        method: "POST",
        body: { label: label.trim(), periodStart: start, periodEnd: end },
      });
      await reloadPeriods();
      setPeriodId(result.period.id);
      setLabel("");
      setStart("");
      setEnd("");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader title="Accounting periods" description="A period is the span a set of books is closed for, such as a financial year." />
      {periods.length > 0 ? (
        <TableWrap>
          <Table>
            <thead>
              <tr>
                <Th>Period</Th>
                <Th>From</Th>
                <Th>To</Th>
                <Th>Status</Th>
              </tr>
            </thead>
            <tbody>
              {periods.map((p) => (
                <tr key={p.id}>
                  <Td className="font-medium">{p.label}</Td>
                  <Td>{formatDate(p.period_start)}</Td>
                  <Td>{formatDate(p.period_end)}</Td>
                  <Td>
                    <Badge tone={p.lock_status === "LOCKED" ? "ledger" : "pass"}>{p.lock_status === "LOCKED" ? "Locked" : "Open"}</Badge>
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </TableWrap>
      ) : (
        <Empty title="No accounting period yet">Add one below, then import a file into it.</Empty>
      )}
      {can(role, CAN.createPeriod) ? (
        <CardBody className="border-t border-rule">
          <form onSubmit={create} className="grid items-end gap-3 sm:grid-cols-[1fr_10rem_10rem_auto]">
            <Field label="Label" htmlFor="period-label">
              <Input id="period-label" value={label} onChange={(e) => setLabel(e.target.value)} placeholder="FY 2025-26" required />
            </Field>
            <Field label="Starts" htmlFor="period-start">
              <Input id="period-start" type="date" value={start} onChange={(e) => setStart(e.target.value)} required />
            </Field>
            <Field label="Ends" htmlFor="period-end">
              <Input id="period-end" type="date" value={end} onChange={(e) => setEnd(e.target.value)} required />
            </Field>
            <Button type="submit" loading={busy} disabled={!label.trim() || !start || !end}>
              Add period
            </Button>
          </form>
          {error ? <Notice kind="error" className="mt-3">{error}</Notice> : null}
        </CardBody>
      ) : (
        <CardBody className="border-t border-rule">
          <p className="text-sm text-ink-soft">Adding a period needs a senior accountant, CA or admin.</p>
        </CardBody>
      )}
    </Card>
  );
}

function UploadCard({ companyId, onUploaded }: { companyId: string; onUploaded: () => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ImportResult | null>(null);

  async function upload(event: FormEvent) {
    event.preventDefault();
    if (!file) return;
    setError(null);
    setResult(null);
    setBusy(true);
    try {
      const form = new FormData();
      form.append("companyId", companyId);
      form.append("file", file);
      const out = await apiUpload<ImportResult>("imports", form);
      setResult(out);
      setFile(null);
      if (input.current) input.current.value = "";
      onUploaded();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader title="Upload a journal file" description="An Excel (.xlsx) or CSV export with date, account, debit and credit columns. Nothing reaches the ledger until the accounts are mapped and posted." />
      <CardBody className="space-y-4">
        <form onSubmit={upload} className="flex flex-wrap items-end gap-3">
          <Field label="File" htmlFor="import-file" className="min-w-[16rem] flex-1">
            <input
              ref={input}
              id="import-file"
              type="file"
              accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              className="block w-full text-sm text-ink file:mr-3 file:h-10 file:cursor-pointer file:rounded-md file:border file:border-rule file:bg-card file:px-4 file:text-sm file:font-medium hover:file:bg-paper"
            />
          </Field>
          <Button type="submit" loading={busy} disabled={!file}>
            Upload and check
          </Button>
        </form>
        {error ? <Notice kind="error">{error}</Notice> : null}
        {result ? (
          <div className="space-y-3">
            <Notice kind={result.errors > 0 ? "warning" : "success"}>
              Read {result.rows} rows: {result.errors} with errors, {result.warnings} with warnings. Debits <Money value={result.total_debit} /> and credits{" "}
              <Money value={result.total_credit} />.
            </Notice>
            {result.issues.length > 0 ? (
              <TableWrap>
                <Table>
                  <thead>
                    <tr>
                      <Th>Row</Th>
                      <Th>Field</Th>
                      <Th>Severity</Th>
                      <Th>Problem</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.issues.slice(0, MAX_SHOWN_ISSUES).map((issue, i) => (
                      <tr key={i}>
                        <Td>{issue.row}</Td>
                        <Td>{issue.field}</Td>
                        <Td>
                          <Badge tone={issue.severity.toUpperCase() === "ERROR" ? "fail" : "warn"}>{issue.severity}</Badge>
                        </Td>
                        <Td>{issue.message}</Td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
                {result.issues_total > MAX_SHOWN_ISSUES ? (
                  <p className="px-4 py-2 text-xs text-ink-faint">Showing the first {MAX_SHOWN_ISSUES} of {result.issues_total} problems.</p>
                ) : null}
              </TableWrap>
            ) : null}
            <p className="text-sm text-ink-soft">
              Next:{" "}
              <Link href="/mappings" className="font-medium text-ledger underline">
                map the accounts and post to the ledger
              </Link>
              .
            </p>
          </div>
        ) : null}
      </CardBody>
    </Card>
  );
}

function FilesCard({ companyId, refreshKey }: { companyId: string; refreshKey: number }) {
  const { data, error, loading } = useApi<{ files: SourceFile[] }>(`companies/${companyId}/versions/files`, { r: refreshKey });
  return (
    <Card>
      <CardHeader title="Imported files" description="Newest first" actions={<Link href="/versions" className="text-sm font-medium text-ledger">Compare two files</Link>} />
      {error ? (
        <CardBody>
          <Notice kind="error">{error}</Notice>
        </CardBody>
      ) : null}
      {loading && !data ? <Loading /> : null}
      {data && data.files.length === 0 ? <Empty title="Nothing imported yet" /> : null}
      {data && data.files.length > 0 ? (
        <TableWrap>
          <Table>
            <thead>
              <tr>
                <Th>File</Th>
                <Th>Uploaded</Th>
                <Th>By</Th>
                <Th align="right">Rows</Th>
                <Th align="right">Errors</Th>
                <Th align="right">Debit</Th>
                <Th align="right">In ledger</Th>
                <Th>Status</Th>
              </tr>
            </thead>
            <tbody>
              {data.files.map((f) => (
                <tr key={f.id}>
                  <Td className="font-medium">{f.filename}</Td>
                  <Td className="whitespace-nowrap text-ink-soft">{formatDateTime(f.uploaded_at)}</Td>
                  <Td>
                    <Who id={f.uploaded_by} />
                  </Td>
                  <Td align="right">{f.rows}</Td>
                  <Td align="right">{f.rows_with_errors}</Td>
                  <Td align="right">
                    <Money value={f.total_debit} />
                  </Td>
                  <Td align="right">
                    {f.rows_posted_to_ledger} / {f.rows}
                  </Td>
                  <Td>
                    <StatusBadge status={f.status} />
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </TableWrap>
      ) : null}
    </Card>
  );
}

function Imports({ companyId, role }: { companyId: string; role: Role }) {
  const [refreshKey, setRefreshKey] = useState(0);
  return (
    <div className="space-y-6">
      <PeriodsCard companyId={companyId} role={role} />
      <UploadCard companyId={companyId} onUploaded={() => setRefreshKey((n) => n + 1)} />
      <FilesCard companyId={companyId} refreshKey={refreshKey} />
    </div>
  );
}

export default function ImportsPage() {
  return (
    <>
      <PageHeader title="Imports" description="Bring a company's journal in from Excel or CSV. Every row is checked on the way in, and nothing is posted to the ledger until its accounts are mapped." />
      <Gate>{({ company, role }) => <Imports key={company.id} companyId={company.id} role={role} />}</Gate>
    </>
  );
}