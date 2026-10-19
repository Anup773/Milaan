"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";
import { PageHeader } from "@/components/common/page-header";
import { Gate } from "@/components/common/gate";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Field, Input, Select } from "@/components/ui/form";
import { Table, TableWrap, Td, Th } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Money } from "@/components/common/money";
import { Loading, Notice } from "@/components/common/notice";
import { api, errorMessage } from "@/lib/api-client";
import { useApi } from "@/lib/use-api";
import type { SheetCheck, SheetsImportResult, SheetsStatus } from "@/lib/sheets-types";

const MAX_SHOWN_ISSUES = 25;

function Result({ result }: { result: SheetsImportResult }) {
  return (
    <div className="space-y-3">
      <Notice kind={result.errors > 0 ? "warning" : "success"}>
        Read {result.rows} rows from {result.sheet.label}: {result.errors} with errors, {result.warnings} with warnings. Debits <Money value={result.total_debit} /> and
        credits <Money value={result.total_credit} />.
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
          {result.issues_total > MAX_SHOWN_ISSUES ? <p className="px-4 py-2 text-xs text-ink-faint">Showing the first {MAX_SHOWN_ISSUES} of {result.issues_total} problems.</p> : null}
        </TableWrap>
      ) : null}
      <p className="text-sm text-ink-soft">
        Next:{" "}
        <Link href="/mappings" className="font-medium text-ledger underline">
          map the account names and post to the ledger
        </Link>
        .
      </p>
    </div>
  );
}

function StatusCard() {
  const { data, error, loading } = useApi<SheetsStatus>("sheets/status");
  return (
    <Card>
      <CardHeader title="How sheets are read" />
      <CardBody className="space-y-3">
        {loading && !data ? <Loading /> : null}
        {error ? <Notice kind="error">{error}</Notice> : null}
        {data ? (
          <>
            <div className="flex flex-wrap items-center gap-2">
              {data.mode === "service_account" ? <Badge tone="pass">Private sheets enabled</Badge> : null}
              {data.mode === "public_link" ? <Badge tone="info">Shared-link sheets only</Badge> : null}
              {data.mode === "service_account_error" ? <Badge tone="fail">Service account problem</Badge> : null}
            </div>
            <Notice kind={data.mode === "service_account_error" ? "error" : "info"}>{data.message}</Notice>
            {data.service_account_email ? (
              <p className="text-sm text-ink-soft">
                Share each sheet with <strong className="break-all text-ink">{data.service_account_email}</strong> as a Viewer.
              </p>
            ) : null}
          </>
        ) : null}
      </CardBody>
    </Card>
  );
}

function ImportCard({ companyId }: { companyId: string }) {
  const [url, setUrl] = useState("");
  const [checking, setChecking] = useState(false);
  const [checked, setChecked] = useState<{ url: string; info: SheetCheck } | null>(null);
  const [tab, setTab] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<SheetsImportResult | null>(null);

  async function check(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setResult(null);
    setChecked(null);
    setChecking(true);
    try {
      const info = await api<SheetCheck>("sheets/check", { method: "POST", body: { url: url.trim() } });
      setChecked({ url: url.trim(), info });
      setTab(info.suggested_tab ?? "");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setChecking(false);
    }
  }

  async function importIt() {
    if (!checked) return;
    setError(null);
    setResult(null);
    setBusy(true);
    try {
      setResult(await api<SheetsImportResult>("sheets/import", { method: "POST", body: { companyId, url: checked.url, tab: tab || undefined } }));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const info = checked?.info;
  return (
    <Card>
      <CardHeader
        title="Import a Google Sheet"
        description="One tab of journal entries with date, account, debit and credit columns, the same layout as an Excel or CSV import. Nothing reaches the ledger until the accounts are mapped and posted."
      />
      <CardBody className="space-y-4">
        <form onSubmit={check} className="flex flex-wrap items-end gap-3">
          <Field label="Google Sheets link" htmlFor="sheet-url" className="min-w-[20rem] flex-1" hint="Open the sheet's tab in Google Sheets and copy the address from the browser.">
            <Input id="sheet-url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://docs.google.com/spreadsheets/d/..." required />
          </Field>
          <Button type="submit" variant="secondary" loading={checking} disabled={!url.trim()}>
            Check the sheet
          </Button>
        </form>
        {error ? <Notice kind="error">{error}</Notice> : null}

        {info ? (
          <div className="space-y-3 border-t border-rule pt-4">
            {info.mode === "service_account" ? (
              <>
                <p className="text-sm">
                  Found <strong>{info.title}</strong> with {info.tabs.length} {info.tabs.length === 1 ? "tab" : "tabs"}.
                </p>
                <Field label="Tab to import" htmlFor="sheet-tab" className="max-w-sm">
                  <Select id="sheet-tab" value={tab} onChange={(e) => setTab(e.target.value)}>
                    {info.tabs.map((t) => (
                      <option key={t.gid} value={t.title}>
                        {t.title}
                      </option>
                    ))}
                  </Select>
                </Field>
              </>
            ) : (
              <Notice kind="success">The sheet is reachable ({info.rows_seen} rows seen). The tab in your link is imported; with no tab in the link, the first tab is.</Notice>
            )}
            <Button onClick={() => void importIt()} loading={busy}>
              Import and check
            </Button>
          </div>
        ) : null}
        {result ? <Result result={result} /> : null}
      </CardBody>
    </Card>
  );
}

export default function SheetsPage() {
  return (
    <>
      <PageHeader
        title="Google Sheets"
        description="Bring a company's journal in from a Google Sheet. It goes through the same checks as an Excel or CSV import."
      />
      <Gate>
        {({ company }) => (
          <div className="space-y-6">
            <StatusCard />
            <ImportCard key={company.id} companyId={company.id} />
          </div>
        )}
      </Gate>
    </>
  );
}