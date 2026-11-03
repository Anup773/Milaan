"use client";

import { useState } from "react";
import { PageHeader } from "@/components/common/page-header";
import { Gate } from "@/components/common/gate";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Table, TableWrap, Td, Th } from "@/components/ui/table";
import { Empty, Loading, Notice } from "@/components/common/notice";
import { Money } from "@/components/common/money";
import { MovementForm, kindLabel } from "@/components/tax/MovementForm";
import { PasteBox } from "@/components/tax/PasteBox";
import { RatesCard } from "@/components/tax/RatesCard";
import { api, errorMessage } from "@/lib/api-client";
import { formatDate } from "@/lib/format";
import { useApi } from "@/lib/use-api";
import type { TaxColumn, TaxMovement, TaxRow, TaxSchedule } from "@/lib/tax-dep-types";

/** AD date (YYYY-MM-DD) moved by whole days, with no time zone in the way. */
function shiftDay(iso: string, days: number): string {
  const [y, m, d] = iso.split("-").map(Number);
  const t = new Date(Date.UTC(y, m - 1, d + days));
  return `${t.getUTCFullYear()}-${String(t.getUTCMonth() + 1).padStart(2, "0")}-${String(t.getUTCDate()).padStart(2, "0")}`;
}

function Cell({ column, row }: { column: TaxColumn; row: Record<string, unknown> }) {
  const v = row[column.key];
  if (typeof v !== "string" || v === "") return <>{column.money ? <Money value="0" /> : "-"}</>;
  return column.money ? <Money value={v} /> : <>{v}</>;
}

function ScheduleTable({ schedule }: { schedule: TaxSchedule }) {
  const withNotes = schedule.pools.filter((p) => Array.isArray(p.notes) && p.notes.length > 0);
  if (schedule.pools.length === 0) {
    return <Empty title="Nothing to show for this fiscal year">Add an opening balance or an addition below, in this year or an earlier one, and the schedule works itself out.</Empty>;
  }
  return (
    <>
      <TableWrap>
        <Table>
          <thead>
            <tr>
              {schedule.columns.map((c) => (
                <Th key={c.key} align={c.money ? "right" : "left"}>
                  {c.label}
                </Th>
              ))}
            </tr>
          </thead>
          <tbody>
            {schedule.pools.map((row: TaxRow) => (
              <tr key={row.pool}>
                {schedule.columns.map((c, i) => (
                  <Td key={c.key} align={c.money ? "right" : "left"} className={i === 0 ? "whitespace-nowrap font-medium" : undefined}>
                    <Cell column={c} row={row} />
                    {i === 0 && row.rate_source === "company" ? (
                      <Badge tone="info" className="ml-2">
                        Company rate
                      </Badge>
                    ) : null}
                  </Td>
                ))}
              </tr>
            ))}
            <tr className="bg-paper/60 font-semibold">
              {schedule.columns.map((c, i) => (
                <Td key={c.key} align={c.money ? "right" : "left"}>
                  {i === 0 ? "Total" : c.money && schedule.totals[c.key] !== undefined ? <Money value={schedule.totals[c.key]} /> : null}
                </Td>
              ))}
            </tr>
          </tbody>
        </Table>
      </TableWrap>
      {withNotes.length > 0 ? (
        <ul className="space-y-1 border-t border-rule px-5 py-3 text-xs text-ink-soft">
          {withNotes.map((p) => (
            <li key={p.pool}>
              <span className="font-medium text-ink">{p.pool}:</span> {(p.notes as string[]).join(" ")}
            </li>
          ))}
        </ul>
      ) : null}
    </>
  );
}

function AssetLines({ schedule }: { schedule: TaxSchedule }) {
  if (schedule.lines.length === 0) return null;
  return (
    <Card>
      <CardHeader title="Each asset" description="What each asset gets in this fiscal year, with the convention it was placed in service under." />
      <TableWrap>
        <Table>
          <thead>
            <tr>
              {schedule.line_columns.map((c) => (
                <Th key={c.key} align={c.money ? "right" : "left"}>
                  {c.label}
                </Th>
              ))}
            </tr>
          </thead>
          <tbody>
            {schedule.lines.map((line) => (
              <tr key={line.asset}>
                {schedule.line_columns.map((c) => (
                  <Td key={c.key} align={c.money ? "right" : "left"} className={c.key === "placed_in_service" || c.key === "pool" ? "whitespace-nowrap" : undefined}>
                    {c.key === "placed_in_service" ? formatDate(line[c.key]) : <Cell column={c} row={line} />}
                  </Td>
                ))}
              </tr>
            ))}
          </tbody>
        </Table>
      </TableWrap>
    </Card>
  );
}

function detailText(m: TaxMovement): string {
  return Object.entries(m.details)
    .map(([k, v]) => (v === true ? k.replace(/_/g, " ") : `${k.replace(/_/g, " ")} ${v}`))
    .join(", ");
}

function Inputs({ companyId, schedule, reload }: { companyId: string; schedule: TaxSchedule; reload: () => void }) {
  const [mode, setMode] = useState<"none" | "add" | "paste">("none");
  const [editing, setEditing] = useState<TaxMovement | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  async function remove(m: TaxMovement) {
    setBusy(m.id);
    setError(null);
    try {
      await api(`companies/${companyId}/tax-depreciation/movements/${m.id}`, { method: "DELETE" });
      reload();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  const done = () => {
    setMode("none");
    setEditing(null);
    reload();
  };
  const scheme = schedule.scheme;
  return (
    <Card>
      <CardHeader
        title="What the schedule is worked from"
        description={
          scheme === "US"
            ? "Every asset, with the date it was placed in service. Earlier years are worked out from these, so an asset bought years ago is entered once with its original date."
            : "Opening balances, additions and disposals. Each year's opening balance follows from the year before; enter an opening balance only for the first year (or to restart a pool)."
        }
        actions={
          schedule.can_edit ? (
            <>
              <Button size="sm" onClick={() => { setEditing(null); setMode("add"); }}>
                Add an entry
              </Button>
              <Button size="sm" variant="secondary" onClick={() => { setEditing(null); setMode("paste"); }}>
                Paste from a spreadsheet
              </Button>
            </>
          ) : null
        }
      />
      {mode === "add" || editing ? (
        <CardBody className="border-b border-rule">
          <MovementForm key={editing?.id ?? "new"} companyId={companyId} schedule={schedule} editing={editing} onDone={done} onCancel={() => { setMode("none"); setEditing(null); }} />
        </CardBody>
      ) : null}
      {mode === "paste" ? (
        <CardBody className="border-b border-rule">
          <PasteBox companyId={companyId} schedule={schedule} onDone={done} />
        </CardBody>
      ) : null}
      {error ? (
        <div className="p-4">
          <Notice kind="error">{error}</Notice>
        </div>
      ) : null}
      {schedule.movements.length === 0 ? (
        <Empty title="Nothing entered yet" />
      ) : (
        <TableWrap>
          <Table>
            <thead>
              <tr>
                <Th>Date</Th>
                <Th>Fiscal year</Th>
                <Th>What</Th>
                <Th>{scheme === "IN" ? "Block" : scheme === "US" ? "Class" : "Pool"}</Th>
                <Th align="right">Amount</Th>
                <Th>Details</Th>
                <Th />
              </tr>
            </thead>
            <tbody>
              {schedule.movements.map((m) => (
                <tr key={m.id}>
                  <Td className="whitespace-nowrap">{formatDate(m.event_date)}</Td>
                  <Td className="whitespace-nowrap text-ink-soft">{m.fiscal_year}</Td>
                  <Td>{kindLabel(scheme, m.kind)}</Td>
                  <Td className="font-medium">{m.pool}</Td>
                  <Td align="right">
                    <Money value={m.amount} />
                  </Td>
                  <Td className="text-ink-soft">
                    {m.description}
                    {m.description && detailText(m) ? "; " : ""}
                    {detailText(m)}
                  </Td>
                  <Td align="right" className="whitespace-nowrap">
                    {schedule.can_edit ? (
                      <>
                        <Button size="sm" variant="ghost" onClick={() => { setMode("none"); setEditing(m); }}>
                          Change
                        </Button>
                        <Button size="sm" variant="ghost" onClick={() => remove(m)} loading={busy === m.id}>
                          Remove
                        </Button>
                      </>
                    ) : null}
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </TableWrap>
      )}
      {!schedule.can_edit ? <p className="px-5 py-3 text-xs text-ink-faint">Changing these entries is for a senior accountant, CA or admin.</p> : null}
    </Card>
  );
}

function TaxDepreciation({ companyId }: { companyId: string }) {
  const [date, setDate] = useState<string | undefined>(undefined);
  const { data, error, loading, reload } = useApi<TaxSchedule>(`companies/${companyId}/tax-depreciation`, date ? { date } : undefined);
  if (error) return <Notice kind="error">{error}</Notice>;
  if (loading && !data) return <Loading />;
  if (!data) return null;
  const fy = data.fiscal_year;
  return (
    <div className="space-y-5">
      <Card>
        <CardHeader
          title={data.scheme_name}
          description="A memo schedule for the tax return and deferred tax. It posts nothing to the ledger: book depreciation is on the Schedules page."
        />
        <CardBody className="space-y-3">
          {data.warnings.map((w) => (
            <Notice key={w} kind="warning">
              {w}
            </Notice>
          ))}
          <ul className="list-disc space-y-1 pl-5 text-sm text-ink-soft">
            {data.notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title={`Fiscal year ${fy.label}`}
          description={`${formatDate(fy.start)} to ${formatDate(fy.end)}`}
          actions={
            <>
              <Button size="sm" variant="secondary" onClick={() => setDate(shiftDay(fy.start, -1))} disabled={loading}>
                Earlier year
              </Button>
              <Button size="sm" variant="secondary" onClick={() => setDate(shiftDay(fy.end, 1))} disabled={loading}>
                Later year
              </Button>
            </>
          }
        />
        <ScheduleTable schedule={data} />
      </Card>

      <AssetLines schedule={data} />
      <Inputs companyId={companyId} schedule={data} reload={reload} />
      <RatesCard companyId={companyId} schedule={data} onChanged={reload} />
    </div>
  );
}

export default function TaxDepreciationPage() {
  return (
    <>
      <PageHeader
        title="Tax depreciation"
        description="Depreciation for the tax return, by your country's rules: pools A to E in Nepal, blocks of assets in India, MACRS in the United States. Rates are data you can change by company and date."
      />
      <Gate>{({ company }) => <TaxDepreciation key={company.id} companyId={company.id} />}</Gate>
    </>
  );
}