"use client";

import Link from "next/link";
import { useRef, useState, type FormEvent, type ReactNode } from "react";
import { PageHeader } from "@/components/common/page-header";
import { Gate } from "@/components/common/gate";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/form";
import { Table, TableWrap, Td, Th } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Money } from "@/components/common/money";
import { Notice } from "@/components/common/notice";
import { apiUpload, errorMessage } from "@/lib/api-client";
import { formatDate } from "@/lib/format";
import type { BankResult } from "@/lib/bank-types";

const MAX_SHOWN_ISSUES = 25;
const DEFAULT_SUSPENSE = "Bank Statement Suspense";

function Stat({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="rounded-md border border-rule bg-paper px-3.5 py-2.5">
      <div className="text-xs text-ink-faint">{label}</div>
      <div className="mt-0.5 text-sm font-medium text-ink">{children}</div>
    </div>
  );
}

function BalanceCheck({ result }: { result: BankResult }) {
  const b = result.bank;
  if (b.balance_check === "passed") {
    return (
      <Notice kind="success">
        The running balance adds up on every row, from {b.opening_balance !== null ? <Money value={b.opening_balance} /> : "the first row"} to{" "}
        <Money value={b.closing_balance} />. Compare that closing balance with your bank passbook or online statement.
      </Notice>
    );
  }
  if (b.balance_check === "failed") {
    return (
      <Notice kind="warning">
        The running balance does not add up in {b.balance_mismatches} {b.balance_mismatches === 1 ? "place" : "places"}. A row may be missing, repeated or misread just above it. Check the rows
        listed below against the bank&apos;s own statement before importing.
      </Notice>
    );
  }
  return <Notice kind="info">This statement has no balance column, so the running balance could not be checked. Compare the totals with the bank yourself.</Notice>;
}

function Summary({ result }: { result: BankResult }) {
  const b = result.bank;
  return (
    <div className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Transactions">
          {b.transactions} ({b.deposits} in, {b.withdrawals} out)
        </Stat>
        <Stat label="Money in">
          <Money value={b.total_deposits} />
        </Stat>
        <Stat label="Money out">
          <Money value={b.total_withdrawals} />
        </Stat>
        <Stat label="Dates">
          {b.first_date ? `${formatDate(b.first_date)} to ${formatDate(b.last_date)}` : "-"}
        </Stat>
      </div>
      <BalanceCheck result={result} />
      {b.order === "newest_first" ? <p className="text-sm text-ink-soft">This statement lists the newest transaction first; it was checked in date order.</p> : null}
      {b.duplicates > 0 ? (
        <Notice kind="warning">
          {b.duplicates} {b.duplicates === 1 ? "transaction is" : "transactions are"} already in an earlier import and will not be posted again.
        </Notice>
      ) : null}
      {b.unreadable_rows > 0 ? (
        <Notice kind="warning">
          {b.unreadable_rows} {b.unreadable_rows === 1 ? "row" : "rows"} could not be read. They are kept as errors and will not be posted.
        </Notice>
      ) : null}
      {b.skipped_rows > 0 ? <p className="text-sm text-ink-soft">{b.skipped_rows} other rows (opening balance, totals, blank or zero-amount lines) were left out on purpose.</p> : null}
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
    </div>
  );
}

function StatementCard({ companyId }: { companyId: string }) {
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [bankName, setBankName] = useState("");
  const [suspense, setSuspense] = useState(DEFAULT_SUSPENSE);
  const [checking, setChecking] = useState(false);
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [checked, setChecked] = useState<{ file: File; bank: string; suspense: string; result: BankResult } | null>(null);
  const [imported, setImported] = useState<BankResult | null>(null);

  const bank = bankName.trim();
  const susp = suspense.trim();
  // The import button only appears for exactly what was checked: change the file or a name and it has to be checked again.
  const fresh = checked !== null && checked.file === file && checked.bank === bank && checked.suspense === susp;
  const newCount = checked ? checked.result.bank.transactions - checked.result.bank.duplicates : 0;
  const importedNew = imported ? imported.bank.transactions - imported.bank.duplicates : 0;

  function formData() {
    const form = new FormData();
    form.append("companyId", companyId);
    form.append("bankAccount", bank);
    form.append("suspenseAccount", susp);
    form.append("file", file as File);
    return form;
  }

  async function check(event: FormEvent) {
    event.preventDefault();
    if (!file) return;
    setError(null);
    setImported(null);
    setChecked(null);
    setChecking(true);
    try {
      const result = await apiUpload<BankResult>("bank/preview", formData());
      setChecked({ file, bank, suspense: susp, result });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setChecking(false);
    }
  }

  async function importIt() {
    if (!file || !fresh) return;
    setError(null);
    setImporting(true);
    try {
      setImported(await apiUpload<BankResult>("bank/import", formData()));
      setChecked(null);
      setFile(null);
      if (input.current) input.current.value = "";
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setImporting(false);
    }
  }

  return (
    <Card>
      <CardHeader
        title="Import a bank statement"
        description="Upload the statement as a CSV or Excel (.xlsx) file from your bank's website. It is checked first and nothing is saved until you press Import."
      />
      <CardBody className="space-y-4">
        <form onSubmit={check} className="space-y-4">
          <div className="flex flex-wrap gap-3">
            <Field label="Bank account name" htmlFor="bank-name" className="min-w-[14rem] flex-1" hint="The name of this bank account in your books, for example HDFC Bank.">
              <Input id="bank-name" value={bankName} onChange={(e) => setBankName(e.target.value)} placeholder="HDFC Bank" required maxLength={150} />
            </Field>
            <Field label="Suspense account name" htmlFor="bank-suspense" className="min-w-[14rem] flex-1" hint="Holds each amount until you move it to the real account.">
              <Input id="bank-suspense" value={suspense} onChange={(e) => setSuspense(e.target.value)} required maxLength={150} />
            </Field>
          </div>
          <div className="flex flex-wrap items-end gap-3">
            <Field label="Statement file" htmlFor="bank-file" className="min-w-[16rem] flex-1">
              <input
                ref={input}
                id="bank-file"
                type="file"
                accept=".csv,.xlsx,.xlsm,.xls"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                className="block w-full text-sm text-ink file:mr-3 file:h-10 file:cursor-pointer file:rounded-md file:border file:border-rule file:bg-card file:px-4 file:text-sm file:font-medium hover:file:bg-paper"
              />
            </Field>
            <Button type="submit" variant="secondary" loading={checking} disabled={!file || !bank || !susp}>
              Check the statement
            </Button>
          </div>
        </form>
        {error ? <Notice kind="error">{error}</Notice> : null}

        {checked ? (
          <div className="space-y-4 border-t border-rule pt-4">
            <Summary result={checked.result} />
            {fresh ? (
              <div className="flex flex-wrap items-center gap-3">
                <Button onClick={() => void importIt()} loading={importing} disabled={newCount <= 0}>
                  Import {newCount} {newCount === 1 ? "transaction" : "transactions"}
                </Button>
                {checked.result.errors > 0 ? <span className="text-sm text-ink-soft">Rows with errors are saved but never posted.</span> : null}
              </div>
            ) : (
              <Notice kind="info">You changed the file or a name. Check the statement again before importing.</Notice>
            )}
          </div>
        ) : null}

        {imported ? (
          <div className="space-y-3 border-t border-rule pt-4">
            <Notice kind={imported.errors > 0 ? "warning" : "success"}>
              Saved {importedNew} new {importedNew === 1 ? "transaction" : "transactions"} ({imported.rows} ledger lines): <Money value={imported.bank.total_deposits} /> in and{" "}
              <Money value={imported.bank.total_withdrawals} /> out in this statement. {imported.errors} with errors, {imported.warnings} with warnings.
              {imported.bank.duplicates > 0 ? ` ${imported.bank.duplicates} already imported earlier ${imported.bank.duplicates === 1 ? "was" : "were"} kept as errors and will not be posted again.` : ""}
            </Notice>
            <p className="text-sm text-ink-soft">
              Next:{" "}
              <Link href="/mappings" className="font-medium text-ledger underline">
                map &ldquo;{bank || "your bank"}&rdquo; and &ldquo;{susp || DEFAULT_SUSPENSE}&rdquo; to your accounts and post
              </Link>
              . Then move each suspense amount to its real account with an adjustment.
            </p>
          </div>
        ) : null}
      </CardBody>
    </Card>
  );
}

export default function BankPage() {
  return (
    <>
      <PageHeader
        title="Bank statements"
        description="Bring a bank statement in. Each transaction becomes a balanced pair of lines, bank account against a suspense account, and goes through the same checks as every other import."
      />
      <Gate>{({ company }) => <StatementCard key={company.id} companyId={company.id} />}</Gate>
    </>
  );
}