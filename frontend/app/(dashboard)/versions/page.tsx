"use client";

import { useState } from "react";
import { PageHeader } from "@/components/common/page-header";
import { Gate } from "@/components/common/gate";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Field, Select } from "@/components/ui/form";
import { Button } from "@/components/ui/button";
import { Table, TableWrap, Td, Th } from "@/components/ui/table";
import { Badge, type Tone } from "@/components/ui/badge";
import { Empty, Loading, Notice } from "@/components/common/notice";
import { Money, Delta } from "@/components/common/money";
import { Stat } from "@/components/common/stat";
import { useApi } from "@/lib/use-api";
import { formatDate, formatDateTime } from "@/lib/format";
import type { SourceFile, VersionChange, VersionCompare } from "@/lib/types";

const KIND_TONE: Record<VersionChange["kind"], Tone> = { CHANGED: "warn", ADDED: "pass", REMOVED: "fail", UNCHANGED: "neutral" };
const KINDS: VersionChange["kind"][] = ["CHANGED", "ADDED", "REMOVED"];

function Side({ row }: { row: VersionChange["old"] }) {
  if (!row) return <span className="text-ink-faint">-</span>;
  return (
    <div className="space-y-0.5">
      <div className="font-medium">{row.account_ref}</div>
      <div className="text-xs text-ink-soft">
        row {row.row_number}
        {row.reference ? ` - ${row.reference}` : ""}
        {row.transaction_date ? ` - ${formatDate(row.transaction_date)}` : ""}
      </div>
      <div className="num text-xs">
        Dr {row.debit} / Cr {row.credit}
      </div>
    </div>
  );
}

function Compare({ companyId, baseId, compareId }: { companyId: string; baseId: string; compareId: string }) {
  const [kinds, setKinds] = useState<VersionChange["kind"][]>(KINDS);
  const [includeUnchanged, setIncludeUnchanged] = useState(false);
  const { data, error, loading } = useApi<VersionCompare>(`companies/${companyId}/versions/compare`, {
    baseFileId: baseId,
    compareFileId: compareId,
    kind: includeUnchanged ? [...kinds, "UNCHANGED"].join(",") : kinds.join(","),
    includeUnchanged: includeUnchanged ? "true" : undefined,
    limit: 500,
  });

  if (loading && !data) return <Loading label="Comparing..." />;
  if (error) return <Notice kind="error">{error}</Notice>;
  if (!data) return null;
  const { summary, totals } = data;

  return (
    <div className="space-y-6">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Changed rows" value={summary.changed} tone={summary.changed ? "warn" : undefined} />
        <Stat label="Added rows" value={summary.added} />
        <Stat label="Removed rows" value={summary.removed} tone={summary.removed ? "fail" : undefined} />
        <Stat label="Unchanged rows" value={summary.unchanged} />
      </div>

      {data.warnings.map((w, i) => (
        <Notice key={i} kind="warning">
          {w}
        </Notice>
      ))}
      <p className="text-sm text-ink-soft">
        This only compares the two files. It changes nothing in the ledger; to turn a difference into a correction, propose an adjustment.
      </p>

      <Card>
        <CardHeader title="Totals" />
        <TableWrap>
          <Table>
            <thead>
              <tr>
                <Th />
                <Th align="right">Rows</Th>
                <Th align="right">Debit</Th>
                <Th align="right">Credit</Th>
                <Th>Balanced</Th>
              </tr>
            </thead>
            <tbody>
              {(
                [
                  ["Older file", data.base.filename, totals.base],
                  ["Newer file", data.compare.filename, totals.compare],
                ] as const
              ).map(([label, name, t]) => (
                <tr key={label}>
                  <Td>
                    <div className="font-medium">{label}</div>
                    <div className="text-xs text-ink-soft">{name}</div>
                  </Td>
                  <Td align="right">{t.rows}</Td>
                  <Td align="right">
                    <Money value={t.total_debit} />
                  </Td>
                  <Td align="right">
                    <Money value={t.total_credit} />
                  </Td>
                  <Td>{t.in_balance ? <Badge tone="pass">Yes</Badge> : <Badge tone="fail">No</Badge>}</Td>
                </tr>
              ))}
              <tr className="bg-paper/60 font-semibold">
                <Td>Difference</Td>
                <Td />
                <Td align="right">
                  <Delta value={totals.delta_debit} goodWhen="neutral" />
                </Td>
                <Td align="right">
                  <Delta value={totals.delta_credit} goodWhen="neutral" />
                </Td>
                <Td />
              </tr>
            </tbody>
          </Table>
        </TableWrap>
      </Card>

      {data.by_account.length > 0 ? (
        <Card>
          <CardHeader title="By account" description="Where the two files disagree" />
          <TableWrap>
            <Table>
              <thead>
                <tr>
                  <Th>Account</Th>
                  <Th align="right">Older debit</Th>
                  <Th align="right">Older credit</Th>
                  <Th align="right">Newer debit</Th>
                  <Th align="right">Newer credit</Th>
                  <Th align="right">Net change</Th>
                </tr>
              </thead>
              <tbody>
                {data.by_account.map((a) => (
                  <tr key={a.account_key}>
                    <Td>
                      <div className="font-medium">{a.account ? `${a.account.code} ${a.account.name}` : a.label}</div>
                      {!a.account ? <div className="text-xs text-warn">Not mapped to an account yet</div> : null}
                    </Td>
                    <Td align="right">
                      <Money value={a.base_debit} />
                    </Td>
                    <Td align="right">
                      <Money value={a.base_credit} />
                    </Td>
                    <Td align="right">
                      <Money value={a.compare_debit} />
                    </Td>
                    <Td align="right">
                      <Money value={a.compare_credit} />
                    </Td>
                    <Td align="right">
                      <Delta value={a.net_change} goodWhen="neutral" />
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </TableWrap>
        </Card>
      ) : null}

      {data.by_period.length > 0 ? (
        <Card>
          <CardHeader title="By accounting period" />
          <TableWrap>
            <Table>
              <thead>
                <tr>
                  <Th>Period</Th>
                  <Th>Status</Th>
                  <Th align="right">Changed rows</Th>
                  <Th align="right">Net change</Th>
                </tr>
              </thead>
              <tbody>
                {data.by_period.map((p) => (
                  <tr key={p.period_id}>
                    <Td className="font-medium">{p.label}</Td>
                    <Td>
                      <Badge tone={p.locked ? "ledger" : "pass"}>{p.locked ? "Locked" : "Open"}</Badge>
                      {p.affected && p.locked ? <span className="ml-2 text-xs text-warn">must be reopened before a correction</span> : null}
                    </Td>
                    <Td align="right">{p.changed_rows}</Td>
                    <Td align="right">
                      <Delta value={p.net_change} goodWhen="neutral" />
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </TableWrap>
        </Card>
      ) : null}

      <Card>
        <CardHeader title="Row by row" description={`${data.changes_total} difference${data.changes_total === 1 ? "" : "s"}${data.changes.length < data.changes_total ? `, showing the first ${data.changes.length}` : ""}`} />
        <div className="flex flex-wrap items-center gap-4 border-b border-rule px-5 py-3 text-sm">
          {KINDS.map((k) => (
            <label key={k} className="flex items-center gap-2">
              <input
                type="checkbox"
                className="h-4 w-4 accent-[#1f5c47]"
                checked={kinds.includes(k)}
                onChange={(e) => setKinds((cur) => (e.target.checked ? [...cur, k] : cur.filter((x) => x !== k)))}
              />
              {k === "CHANGED" ? "Changed" : k === "ADDED" ? "Added" : "Removed"}
            </label>
          ))}
          <label className="flex items-center gap-2">
            <input type="checkbox" className="h-4 w-4 accent-[#1f5c47]" checked={includeUnchanged} onChange={(e) => setIncludeUnchanged(e.target.checked)} />
            Unchanged
          </label>
        </div>
        {data.changes.length === 0 ? (
          <Empty title="No rows match">Adjust the filters above.</Empty>
        ) : (
          <TableWrap>
            <Table>
              <thead>
                <tr>
                  <Th>What happened</Th>
                  <Th>Older file</Th>
                  <Th>Newer file</Th>
                  <Th>What differs</Th>
                </tr>
              </thead>
              <tbody>
                {data.changes.map((c, i) => (
                  <tr key={i}>
                    <Td>
                      <Badge tone={KIND_TONE[c.kind]}>{c.kind === "CHANGED" ? "Changed" : c.kind === "ADDED" ? "Added" : c.kind === "REMOVED" ? "Removed" : "Unchanged"}</Badge>
                      {c.old_posted ? <div className="mt-1 text-xs text-warn">older row is already in the ledger</div> : null}
                    </Td>
                    <Td>
                      <Side row={c.old} />
                    </Td>
                    <Td>
                      <Side row={c.new} />
                    </Td>
                    <Td>
                      {c.fields && c.fields.length > 0 ? (
                        <ul className="space-y-0.5 text-xs">
                          {c.fields.map((f) => (
                            <li key={f.field}>
                              <span className="font-medium">{f.field}</span>: <span className="text-ink-soft">{f.old ?? "-"}</span> to <span className="font-medium">{f.new ?? "-"}</span>
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <span className="text-ink-faint">-</span>
                      )}
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </TableWrap>
        )}
      </Card>
    </div>
  );
}

function Versions({ companyId }: { companyId: string }) {
  const files = useApi<{ files: SourceFile[] }>(`companies/${companyId}/versions/files`);
  const list = files.data?.files ?? [];
  const [base, setBase] = useState("");
  const [compare, setCompare] = useState("");
  const [go, setGo] = useState<{ base: string; compare: string } | null>(null);

  // older file defaults to the second newest, newer to the newest (the API lists newest first)
  const baseId = base || list[1]?.id || "";
  const compareId = compare || list[0]?.id || "";
  const label = (f: SourceFile) => `${f.filename} - ${formatDateTime(f.uploaded_at)} (${f.rows} rows)`;

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader title="Choose two imports" description="An older one and a newer one, for example a re-exported file after corrections" />
        <CardBody>
          {files.error ? <Notice kind="error">{files.error}</Notice> : null}
          {files.loading && !files.data ? <Loading /> : null}
          {files.data && list.length < 2 ? <Empty title="You need two imports to compare">Import a second file on the Imports page first.</Empty> : null}
          {list.length >= 2 ? (
            <div className="flex flex-wrap items-end gap-3">
              <Field label="Older file" htmlFor="v-base" className="min-w-[16rem] flex-1">
                <Select id="v-base" value={baseId} onChange={(e) => setBase(e.target.value)}>
                  {list.map((f) => (
                    <option key={f.id} value={f.id}>
                      {label(f)}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="Newer file" htmlFor="v-compare" className="min-w-[16rem] flex-1">
                <Select id="v-compare" value={compareId} onChange={(e) => setCompare(e.target.value)}>
                  {list.map((f) => (
                    <option key={f.id} value={f.id}>
                      {label(f)}
                    </option>
                  ))}
                </Select>
              </Field>
              <Button disabled={!baseId || !compareId || baseId === compareId} onClick={() => setGo({ base: baseId, compare: compareId })}>
                Compare
              </Button>
            </div>
          ) : null}
          {baseId && compareId && baseId === compareId ? <p className="mt-2 text-sm text-ink-soft">Choose two different files.</p> : null}
        </CardBody>
      </Card>
      {go ? <Compare key={`${go.base}:${go.compare}`} companyId={companyId} baseId={go.base} compareId={go.compare} /> : null}
    </div>
  );
}

export default function VersionsPage() {
  return (
    <>
      <PageHeader title="Versions" description="Compare two imports of the same books to see what changed, was added or was removed, and whether the change touches a locked period." />
      <Gate>{({ company }) => <Versions key={company.id} companyId={company.id} />}</Gate>
    </>
  );
}
