"use client";

import Link from "next/link";
import { useRef, useState, type FormEvent } from "react";
import { PageHeader } from "@/components/common/page-header";
import { Gate } from "@/components/common/gate";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Field, Input, Select } from "@/components/ui/form";
import { Table, TableWrap, Td, Th } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Money } from "@/components/common/money";
import { Notice } from "@/components/common/notice";
import { api, apiUpload, errorMessage } from "@/lib/api-client";
import { formatDate } from "@/lib/format";
import type { Period } from "@/lib/types";
import type { TallyImportResult, TallyStatus } from "@/lib/tally-types";

const MAX_SHOWN_ISSUES = 25;

function Result({ result }: { result: TallyImportResult }) {
  const t = result.tally;
  const skipped = t.skipped_cancelled + t.skipped_optional + t.skipped_non_accounting + t.skipped_no_ledger_lines;
  return (
    <div className="space-y-3">
      <Notice kind={result.errors > 0 ? "warning" : "success"}>
        Read {t.vouchers_imported} vouchers as {result.rows} ledger lines
        {t.first_date && t.last_date ? ` dated ${formatDate(t.first_date)} to ${formatDate(t.last_date)}` : ""}. {result.errors} with errors, {result.warnings} with
        warnings. Debits <Money value={result.total_debit} /> and credits <Money value={result.total_credit} />.
      </Notice>
      {skipped > 0 || t.zero_amount_lines_skipped > 0 ? (
        <p className="text-sm text-ink-soft">
          Left out on purpose: {t.skipped_cancelled} cancelled, {t.skipped_optional} optional, {t.skipped_non_accounting} not accounting entries (orders, delivery notes),{" "}
          {t.skipped_no_ledger_lines} with no ledger lines, and {t.zero_amount_lines_skipped} zero-amount lines.
        </p>
      ) : null}
      {t.unbalanced_vouchers > 0 ? (
        <Notice kind="warning">
          {t.unbalanced_vouchers} {t.unbalanced_vouchers === 1 ? "voucher does" : "vouchers do"} not balance in the data Tally sent. They are marked as errors and will not be posted.
        </Notice>
      ) : null}
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
          {result.issues_total > MAX_SHOWN_ISSUES ? <p className="px-4 py-2 text-xs text-ink-faint">Showing the first {MAX_SHOWN_ISSUES} of {result.issues_total} problems.</p> : null}
        </TableWrap>
      ) : null}
      <p className="text-sm text-ink-soft">
        Next:{" "}
        <Link href="/mappings" className="font-medium text-ledger underline">
          map the ledger names to your accounts and post to the ledger
        </Link>
        .
      </p>
    </div>
  );
}

function LiveCard({ companyId, period }: { companyId: string; period: Period | null }) {
  const [status, setStatus] = useState<TallyStatus | null>(null);
  const [checking, setChecking] = useState(false);
  const [checkError, setCheckError] = useState<string | null>(null);
  const [from, setFrom] = useState(period?.period_start ?? "");
  const [to, setTo] = useState(period?.period_end ?? "");
  const [tallyCompany, setTallyCompany] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<TallyImportResult | null>(null);

  async function check() {
    setChecking(true);
    setCheckError(null);
    try {
      const s = await api<TallyStatus>("tally/status");
      setStatus(s);
      if (s.reachable && s.companies.length === 1) setTallyCompany(s.companies[0]);
    } catch (err) {
      setStatus(null);
      setCheckError(errorMessage(err));
    } finally {
      setChecking(false);
    }
  }

  async function fetchFromTally(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setResult(null);
    if (to < from) {
      setError("The end date cannot be before the start date.");
      return;
    }
    setBusy(true);
    try {
      setResult(await api<TallyImportResult>("tally/import-live", { method: "POST", body: { companyId, fromDate: from, toDate: to, tallyCompany: tallyCompany || undefined } }));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader title="Fetch from Tally" description="Pulls the Day Book straight from a Tally that is open on the same computer as the Milaan API." />
      <CardBody className="space-y-4">
        <div className="flex flex-wrap items-center gap-3">
          <Button variant="secondary" onClick={() => void check()} loading={checking}>
            Check the connection
          </Button>
          {status ? (
            status.reachable ? (
              <Badge tone="pass">Connected to {status.url}</Badge>
            ) : (
              <Badge tone="fail">Not connected</Badge>
            )
          ) : null}
        </div>
        {checkError ? <Notice kind="error">{checkError}</Notice> : null}
        {status && !status.reachable ? <Notice kind="warning">{status.message}</Notice> : null}
        {status?.reachable && status.companies.length === 0 ? <Notice kind="info">Connected, but Tally did not list any open company. Open one in Tally first.</Notice> : null}

        <form onSubmit={fetchFromTally} className="flex flex-wrap items-end gap-3">
          {status?.reachable && status.companies.length > 1 ? (
            <Field label="Tally company" htmlFor="tally-company" className="min-w-[14rem]">
              <Select id="tally-company" value={tallyCompany} onChange={(e) => setTallyCompany(e.target.value)} required>
                <option value="">Choose...</option>
                {status.companies.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </Select>
            </Field>
          ) : (
            <Field label="Tally company" htmlFor="tally-company" hint="Leave empty to use the company open in Tally." className="min-w-[14rem]">
              <Input id="tally-company" value={tallyCompany} onChange={(e) => setTallyCompany(e.target.value)} />
            </Field>
          )}
          <Field label="From" htmlFor="tally-from">
            <Input id="tally-from" type="date" value={from} onChange={(e) => setFrom(e.target.value)} required />
          </Field>
          <Field label="To" htmlFor="tally-to">
            <Input id="tally-to" type="date" value={to} onChange={(e) => setTo(e.target.value)} required />
          </Field>
          <Button type="submit" loading={busy} disabled={!from || !to}>
            Fetch and check
          </Button>
        </form>
        {error ? <Notice kind="error">{error}</Notice> : null}
        {result ? <Result result={result} /> : null}
      </CardBody>
    </Card>
  );
}

function FileCard({ companyId }: { companyId: string }) {
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<TallyImportResult | null>(null);

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
      setResult(await apiUpload<TallyImportResult>("tally/import-file", form));
      setFile(null);
      if (input.current) input.current.value = "";
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader
        title="Upload a Tally XML export"
        description="In Tally open Display > Day Book, press Alt+E (Export), choose the XML format, and save. This works even when Tally is not on the same computer."
      />
      <CardBody className="space-y-4">
        <form onSubmit={upload} className="flex flex-wrap items-end gap-3">
          <Field label="XML file" htmlFor="tally-file" className="min-w-[16rem] flex-1">
            <input
              ref={input}
              id="tally-file"
              type="file"
              accept=".xml,text/xml,application/xml"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              className="block w-full text-sm text-ink file:mr-3 file:h-10 file:cursor-pointer file:rounded-md file:border file:border-rule file:bg-card file:px-4 file:text-sm file:font-medium hover:file:bg-paper"
            />
          </Field>
          <Button type="submit" loading={busy} disabled={!file}>
            Upload and check
          </Button>
        </form>
        {error ? <Notice kind="error">{error}</Notice> : null}
        {result ? <Result result={result} /> : null}
      </CardBody>
    </Card>
  );
}

export default function TallyPage() {
  return (
    <>
      <PageHeader
        title="Tally"
        description="Bring a company's vouchers in from Tally. They go through the same checks as an Excel or CSV import: nothing reaches the ledger until the ledger names are mapped and posted."
      />
      <Gate>
        {({ company, period }) => (
          <div className="space-y-6">
            <LiveCard key={`${company.id}:${period?.id ?? ""}`} companyId={company.id} period={period} />
            <FileCard key={`file:${company.id}`} companyId={company.id} />
          </div>
        )}
      </Gate>
    </>
  );
}