"use client";

import Link from "next/link";
import { useRef, useState, type FormEvent, type ReactNode } from "react";
import { PageHeader } from "@/components/common/page-header";
import { Gate } from "@/components/common/gate";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Field, Input, Select } from "@/components/ui/form";
import { Table, TableWrap, Td, Th } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Money } from "@/components/common/money";
import { Loading, Notice } from "@/components/common/notice";
import { apiUpload, errorMessage } from "@/lib/api-client";
import { useApi } from "@/lib/use-api";
import { formatDate } from "@/lib/format";
import type { RegisterResult, RegisterTemplate, RegisterTemplates } from "@/lib/registers-types";

const MAX_SHOWN_ISSUES = 25;

function Stat({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="rounded-md border border-rule bg-paper px-3.5 py-2.5">
      <div className="text-xs text-ink-faint">{label}</div>
      <div className="mt-0.5 text-sm font-medium text-ink">{children}</div>
    </div>
  );
}

function Summary({ result }: { result: RegisterResult }) {
  const r = result.register;
  return (
    <div className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {r.summary.map((item) => (
          <Stat key={item.label} label={item.label}>
            {item.kind === "money" ? <Money value={item.value} /> : item.value}
          </Stat>
        ))}
        <Stat label="Dates">{r.first_date ? `${formatDate(r.first_date)} to ${formatDate(r.last_date)}` : "-"}</Stat>
      </div>
      {r.credit_notes > 0 ? <p className="text-sm text-ink-soft">{r.credit_notes} negative {r.credit_notes === 1 ? "row was" : "rows were"} treated as credit/debit notes and reverse the usual sides.</p> : null}
      {r.round_off_rows > 0 ? (
        <Notice kind="warning">
          {r.round_off_rows} {r.round_off_rows === 1 ? "row differs" : "rows differ"} from the sum of its parts by 1.00 or less. The difference is booked to the round off account.
        </Notice>
      ) : null}
      {r.duplicates > 0 ? (
        <Notice kind="warning">
          {r.duplicates} {r.duplicates === 1 ? "row is" : "rows are"} already in an earlier import and will not be posted again.
        </Notice>
      ) : null}
      {r.unreadable_rows > 0 ? (
        <Notice kind="warning">
          {r.unreadable_rows} {r.unreadable_rows === 1 ? "row" : "rows"} could not be accepted. They are kept as errors and will not be posted.
        </Notice>
      ) : null}
      {r.date_from_default > 0 ? <p className="text-sm text-ink-soft">The file has no date column, so the voucher date you entered was used.</p> : null}
      {r.skipped_rows > 0 ? <p className="text-sm text-ink-soft">{r.skipped_rows} other rows (totals, blank or all-zero lines) were left out on purpose.</p> : null}
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

function RegisterCard({ companyId, templates }: { companyId: string; templates: RegisterTemplate[] }) {
  const input = useRef<HTMLInputElement>(null);
  const [templateKey, setTemplateKey] = useState(templates[0]?.key ?? "");
  const [names, setNames] = useState<Record<string, string>>({});
  const [partyAccounts, setPartyAccounts] = useState(false);
  const [voucherDate, setVoucherDate] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [checking, setChecking] = useState(false);
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [checked, setChecked] = useState<{ signature: string; file: File; result: RegisterResult } | null>(null);
  const [imported, setImported] = useState<{ result: RegisterResult; template: RegisterTemplate } | null>(null);

  const template = templates.find((t) => t.key === templateKey) ?? templates[0];
  // Only what differs from the default name is sent, so a role left alone always uses the current default.
  const accounts: Record<string, string> = {};
  for (const role of template.roles) {
    const typed = (names[`${template.key}:${role.key}`] ?? "").trim();
    if (typed !== "") accounts[role.key] = typed;
  }
  const party = template.party_accounts_option && partyAccounts;
  const signature = JSON.stringify([template.key, accounts, party, voucherDate]);
  // The import button only appears for exactly what was checked: change the file or a setting and it has to be checked again.
  const fresh = checked !== null && checked.file === file && checked.signature === signature;
  const newCount = checked ? checked.result.register.records - checked.result.register.duplicates : 0;

  function formData() {
    const form = new FormData();
    form.append("companyId", companyId);
    form.append("template", template.key);
    form.append("accounts", JSON.stringify(accounts));
    form.append("partyAccounts", String(party));
    if (voucherDate) form.append("voucherDate", voucherDate);
    form.append("file", file as File);
    return form;
  }

  function reset() {
    setChecked(null);
    setImported(null);
    setError(null);
  }

  async function check(event: FormEvent) {
    event.preventDefault();
    if (!file) return;
    reset();
    setChecking(true);
    try {
      const result = await apiUpload<RegisterResult>("registers/preview", formData());
      setChecked({ signature, file, result });
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
      const result = await apiUpload<RegisterResult>("registers/import", formData());
      setImported({ result, template });
      setChecked(null);
      setFile(null);
      if (input.current) input.current.value = "";
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setImporting(false);
    }
  }

  const importedNew = imported ? imported.result.register.records - imported.result.register.duplicates : 0;
  const noun = template.key === "payroll" ? "row" : template.key === "sales" ? "invoice" : "bill";

  return (
    <Card>
      <CardHeader
        title="Import a register"
        description="Upload the register as a CSV or Excel (.xlsx) file, for example exported from Tally, Zoho, Busy or your payroll software. It is checked first and nothing is saved until you press Import."
      />
      <CardBody className="space-y-4">
        <form onSubmit={check} className="space-y-4">
          <Field label="Register type" htmlFor="reg-template" className="max-w-sm">
            <Select
              id="reg-template"
              value={template.key}
              onChange={(e) => {
                setTemplateKey(e.target.value);
                reset();
              }}
            >
              {templates.map((t) => (
                <option key={t.key} value={t.key}>
                  {t.label}
                </option>
              ))}
            </Select>
          </Field>
          <p className="text-sm text-ink-soft">{template.description}</p>
          <p className="text-xs text-ink-faint">
            Columns it looks for:{" "}
            {template.columns
              .map((c) => `${c.names[0]}${c.required ? "*" : ""}`)
              .join(", ")}
            . (* required{template.key === "payroll" ? "; the date can instead be typed below" : ""})
          </p>

          <div>
            <div className="mb-2 text-sm font-medium text-ink">Account names</div>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {template.roles.map((role) => (
                <Field key={`${template.key}:${role.key}`} label={role.label} htmlFor={`reg-role-${role.key}`}>
                  <Input
                    id={`reg-role-${role.key}`}
                    value={names[`${template.key}:${role.key}`] ?? ""}
                    placeholder={role.default}
                    maxLength={150}
                    onChange={(e) => setNames({ ...names, [`${template.key}:${role.key}`]: e.target.value })}
                  />
                </Field>
              ))}
            </div>
            <p className="mt-1 text-xs text-ink-faint">Leave a box empty to use the name shown inside it. You map these names to your accounts on the Mappings page.</p>
          </div>

          {template.party_accounts_option ? (
            <label className="flex items-center gap-2 text-sm text-ink">
              <input id="reg-party" type="checkbox" checked={partyAccounts} onChange={(e) => setPartyAccounts(e.target.checked)} className="h-4 w-4" />
              Give each customer or supplier its own account (otherwise they all go to the control account above)
            </label>
          ) : null}

          <div className="flex flex-wrap items-end gap-3">
            <Field
              label="Voucher date"
              htmlFor="reg-date"
              hint={template.key === "payroll" ? "Usually the month end. Used when the file has no date column." : "Optional. Used only when the file has no date column."}
            >
              <Input id="reg-date" type="date" value={voucherDate} onChange={(e) => setVoucherDate(e.target.value)} />
            </Field>
            <Field label="Register file" htmlFor="reg-file" className="min-w-[16rem] flex-1">
              <input
                ref={input}
                id="reg-file"
                type="file"
                accept=".csv,.xlsx,.xlsm,.xls"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                className="block w-full text-sm text-ink file:mr-3 file:h-10 file:cursor-pointer file:rounded-md file:border file:border-rule file:bg-card file:px-4 file:text-sm file:font-medium hover:file:bg-paper"
              />
            </Field>
            <Button type="submit" variant="secondary" loading={checking} disabled={!file}>
              Check the register
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
                  Import {newCount} {newCount === 1 ? noun : `${noun}s`}
                </Button>
                {checked.result.errors > 0 ? <span className="text-sm text-ink-soft">Rows with errors are saved but never posted.</span> : null}
              </div>
            ) : (
              <Notice kind="info">You changed the file or a setting. Check the register again before importing.</Notice>
            )}
          </div>
        ) : null}

        {imported ? (
          <div className="space-y-3 border-t border-rule pt-4">
            <Notice kind={imported.result.errors > 0 ? "warning" : "success"}>
              Saved {importedNew} new {importedNew === 1 ? "row" : "rows"} as {imported.result.rows} ledger lines. {imported.result.errors} with errors, {imported.result.warnings} with warnings.
              {imported.result.register.duplicates > 0
                ? ` ${imported.result.register.duplicates} already imported earlier ${imported.result.register.duplicates === 1 ? "was" : "were"} kept as errors and will not be posted again.`
                : ""}
            </Notice>
            <p className="text-sm text-ink-soft">
              Next:{" "}
              <Link href="/mappings" className="font-medium text-ledger underline">
                map the account names to your accounts and post to the ledger
              </Link>
              .
            </p>
          </div>
        ) : null}
      </CardBody>
    </Card>
  );
}

function RegistersLoader({ companyId }: { companyId: string }) {
  const { data, error, loading } = useApi<RegisterTemplates>("registers/templates");
  if (loading && !data) return <Loading />;
  if (error) return <Notice kind="error">{error}</Notice>;
  if (!data || data.templates.length === 0) return <Notice kind="error">No register types are available.</Notice>;
  return <RegisterCard key={companyId} companyId={companyId} templates={data.templates} />;
}

export default function RegistersPage() {
  return (
    <>
      <PageHeader
        title="GST and payroll registers"
        description="Bring a sales register, a purchase register or a payroll register in. Each row becomes a balanced voucher and goes through the same checks as every other import."
      />
      <Gate>{({ company }) => <RegistersLoader companyId={company.id} />}</Gate>
    </>
  );
}