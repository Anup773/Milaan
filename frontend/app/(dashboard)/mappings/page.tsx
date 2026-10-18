"use client";

import { useState, type FormEvent } from "react";
import { PageHeader } from "@/components/common/page-header";
import { Gate } from "@/components/common/gate";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Field, Input, Select } from "@/components/ui/form";
import { Modal } from "@/components/ui/modal";
import { Table, TableWrap, Td, Th } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Empty, Loading, Notice } from "@/components/common/notice";
import { Money } from "@/components/common/money";
import { api, errorMessage } from "@/lib/api-client";
import { useApi } from "@/lib/use-api";
import { CAN, can, type Role } from "@/lib/roles";
import { formatDateTime } from "@/lib/format";
import type { Account, MaterializeResult, SourceFile, UnmappedAccount } from "@/lib/types";

const ACCOUNT_TYPES: Account["account_type"][] = ["Asset", "Liability", "Equity", "Income", "Expense"];

function MapDialog({
  companyId,
  item,
  accounts,
  onClose,
  onMapped,
}: {
  companyId: string;
  item: UnmappedAccount | null;
  accounts: Account[];
  onClose: () => void;
  onMapped: () => void;
}) {
  const [mode, setMode] = useState<"existing" | "new">("existing");
  const [accountId, setAccountId] = useState("");
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [type, setType] = useState<Account["account_type"]>("Expense");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!item) return;
    setError(null);
    setBusy(true);
    try {
      const body =
        mode === "existing"
          ? { accountRef: item.account_ref_key, accountId }
          : { accountRef: item.account_ref_key, newAccount: { code: code.trim(), name: name.trim(), accountType: type } };
      await api(`mappings/${companyId}/confirm`, { method: "POST", body });
      setAccountId("");
      setCode("");
      setName("");
      onMapped();
      onClose();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const ready = mode === "existing" ? !!accountId : !!code.trim() && !!name.trim();

  return (
    <Modal
      open={item !== null}
      onClose={onClose}
      title="Map an account"
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" form="map-form" loading={busy} disabled={!ready}>
            Confirm mapping
          </Button>
        </>
      }
    >
      {item ? (
        <form id="map-form" onSubmit={submit} className="space-y-4">
          <p className="text-sm text-ink-soft">
            The file calls this account <strong className="text-ink">&ldquo;{item.sample_text}&rdquo;</strong> ({item.row_count} {item.row_count === 1 ? "row" : "rows"}). Which account in your chart is it?
          </p>
          <div className="flex gap-2" role="radiogroup" aria-label="How to map">
            <Button type="button" size="sm" variant={mode === "existing" ? "primary" : "secondary"} onClick={() => setMode("existing")}>
              An existing account
            </Button>
            <Button type="button" size="sm" variant={mode === "new" ? "primary" : "secondary"} onClick={() => setMode("new")}>
              A new account
            </Button>
          </div>
          {mode === "existing" ? (
            <Field label="Account" htmlFor="map-account">
              <Select id="map-account" value={accountId} onChange={(e) => setAccountId(e.target.value)}>
                <option value="">Choose an account...</option>
                {accounts.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.code} {a.name} ({a.account_type})
                  </option>
                ))}
              </Select>
            </Field>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Code" htmlFor="new-code">
                <Input id="new-code" value={code} onChange={(e) => setCode(e.target.value)} placeholder="5000" />
              </Field>
              <Field label="Type" htmlFor="new-type">
                <Select id="new-type" value={type} onChange={(e) => setType(e.target.value as Account["account_type"])}>
                  {ACCOUNT_TYPES.map((t) => (
                    <option key={t}>{t}</option>
                  ))}
                </Select>
              </Field>
              <Field label="Name" htmlFor="new-name" className="sm:col-span-2">
                <Input id="new-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Raw material purchases" />
              </Field>
            </div>
          )}
          {error ? <Notice kind="error">{error}</Notice> : null}
        </form>
      ) : null}
    </Modal>
  );
}

function Mappings({ companyId, role }: { companyId: string; role: Role }) {
  const unmapped = useApi<{ unmapped: UnmappedAccount[] }>(`mappings/${companyId}/unmapped`);
  const accounts = useApi<{ accounts: Account[] }>(`companies/${companyId}/accounts`);
  const files = useApi<{ files: SourceFile[] }>(`companies/${companyId}/versions/files`);
  const [target, setTarget] = useState<UnmappedAccount | null>(null);
  const [posting, setPosting] = useState<string | null>(null);
  const [postResult, setPostResult] = useState<{ file: string; result: MaterializeResult } | null>(null);
  const [postError, setPostError] = useState<string | null>(null);
  const canMap = can(role, CAN.confirmMapping);

  async function post(file: SourceFile) {
    setPostError(null);
    setPostResult(null);
    setPosting(file.id);
    try {
      const result = await api<MaterializeResult>(`mappings/${companyId}/source-files/${file.id}/materialize`, { method: "POST", body: {} });
      setPostResult({ file: file.filename, result });
      files.reload();
      unmapped.reload();
    } catch (err) {
      setPostError(errorMessage(err));
    } finally {
      setPosting(null);
    }
  }

  const waiting = files.data?.files.filter((f) => f.rows_posted_to_ledger < f.rows - f.rows_with_errors) ?? [];

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader title="Accounts still to map" description="Names in your files that are not yet tied to an account in the chart of accounts" />
        {unmapped.error ? (
          <CardBody>
            <Notice kind="error">{unmapped.error}</Notice>
          </CardBody>
        ) : null}
        {unmapped.loading && !unmapped.data ? <Loading /> : null}
        {unmapped.data && unmapped.data.unmapped.length === 0 ? <Empty title="Everything is mapped">Every account name in the imported files is tied to an account.</Empty> : null}
        {unmapped.data && unmapped.data.unmapped.length > 0 ? (
          <TableWrap>
            <Table>
              <thead>
                <tr>
                  <Th>Name in the file</Th>
                  <Th align="right">Rows</Th>
                  <Th align="right">First seen at row</Th>
                  <Th />
                </tr>
              </thead>
              <tbody>
                {unmapped.data.unmapped.map((u) => (
                  <tr key={u.account_ref_key}>
                    <Td className="font-medium">{u.sample_text}</Td>
                    <Td align="right">{u.row_count}</Td>
                    <Td align="right">{u.first_row_number}</Td>
                    <Td align="right">
                      {canMap ? (
                        <Button size="sm" onClick={() => setTarget(u)}>
                          Map
                        </Button>
                      ) : null}
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </TableWrap>
        ) : null}
        {!canMap ? (
          <CardBody className="border-t border-rule">
            <p className="text-sm text-ink-soft">Mapping accounts needs an accountant role or above.</p>
          </CardBody>
        ) : null}
      </Card>

      <Card>
        <CardHeader title="Post to the ledger" description="Rows whose accounts are all mapped become journal entries. Rows already posted are never posted twice." />
        {files.error ? (
          <CardBody>
            <Notice kind="error">{files.error}</Notice>
          </CardBody>
        ) : null}
        {files.loading && !files.data ? <Loading /> : null}
        {files.data && files.data.files.length === 0 ? <Empty title="Nothing imported yet" /> : null}
        {files.data && files.data.files.length > 0 ? (
          <TableWrap>
            <Table>
              <thead>
                <tr>
                  <Th>File</Th>
                  <Th>Uploaded</Th>
                  <Th align="right">Debit</Th>
                  <Th align="right">In ledger</Th>
                  <Th />
                </tr>
              </thead>
              <tbody>
                {files.data.files.map((f) => {
                  const pending = waiting.some((w) => w.id === f.id);
                  return (
                    <tr key={f.id}>
                      <Td className="font-medium">{f.filename}</Td>
                      <Td className="whitespace-nowrap text-ink-soft">{formatDateTime(f.uploaded_at)}</Td>
                      <Td align="right">
                        <Money value={f.total_debit} />
                      </Td>
                      <Td align="right">
                        {f.rows_posted_to_ledger} / {f.rows}
                      </Td>
                      <Td align="right">
                        {pending && canMap ? (
                          <Button size="sm" loading={posting === f.id} disabled={posting !== null} onClick={() => void post(f)}>
                            Post to ledger
                          </Button>
                        ) : (
                          <Badge tone={f.rows_posted_to_ledger >= f.rows - f.rows_with_errors ? "pass" : "neutral"}>
                            {f.rows_posted_to_ledger >= f.rows - f.rows_with_errors ? "Posted" : "Waiting"}
                          </Badge>
                        )}
                      </Td>
                    </tr>
                  );
                })}
              </tbody>
            </Table>
          </TableWrap>
        ) : null}
        <CardBody className="space-y-3 border-t border-rule">
          {postError ? <Notice kind="error">{postError}</Notice> : null}
          {postResult ? (
            <Notice kind={postResult.result.blocked.length > 0 ? "warning" : "success"}>
              {postResult.file}: {postResult.result.posted} posted, {postResult.result.already_posted} already posted
              {postResult.result.blocked.length > 0 ? `, ${postResult.result.blocked.length} blocked` : ""}
              {postResult.result.skipped.length > 0 ? `, ${postResult.result.skipped.length} skipped` : ""}.
              {postResult.result.blocked.length > 0 ? " Blocked rows usually sit in a locked period or still have an unmapped account." : ""}
            </Notice>
          ) : null}
        </CardBody>
      </Card>

      <MapDialog
        companyId={companyId}
        item={target}
        accounts={accounts.data?.accounts ?? []}
        onClose={() => setTarget(null)}
        onMapped={() => {
          unmapped.reload();
          accounts.reload();
        }}
      />
    </div>
  );
}

export default function MappingsPage() {
  return (
    <>
      <PageHeader title="Mappings" description="Tie the account names in an imported file to your chart of accounts, then post the rows to the ledger." />
      <Gate>{({ company, role }) => <Mappings key={company.id} companyId={company.id} role={role} />}</Gate>
    </>
  );
}