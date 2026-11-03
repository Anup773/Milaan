"use client";

import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Field, Input, Select } from "@/components/ui/form";
import { Table, TableWrap, Td, Th } from "@/components/ui/table";
import { Notice } from "@/components/common/notice";
import { api, errorMessage } from "@/lib/api-client";
import { formatDate } from "@/lib/format";
import { toAdDate } from "@/lib/tax-dep-paste";
import type { TaxSchedule } from "@/lib/tax-dep-types";

/** The standard rates, the company's own dated rates, and a way to set them. Rates are data: a company's own rate wins from its date. */
export function RatesCard({ companyId, schedule, onChanged }: { companyId: string; schedule: TaxSchedule; onChanged: () => void }) {
  const calendar = schedule.calendar;
  const [pool, setPool] = useState("");
  const [rate, setRate] = useState("");
  const [from, setFrom] = useState("");
  const [note, setNote] = useState("");
  const [presetDate, setPresetDate] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (schedule.scheme === "US") {
    return (
      <Card>
        <CardHeader title="Rates" description="MACRS percentages come from the IRS tables (Publication 946) and are not edited here." />
      </Card>
    );
  }

  const dateHint = calendar === "BS" ? "In BS, for example 2082-04-01. The rate applies to fiscal years ending on or after this date." : "Year-month-day. The rate applies to fiscal years ending on or after this date.";

  async function put(body: Record<string, unknown>) {
    await api(`companies/${companyId}/tax-depreciation/rates`, { method: "PUT", body });
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    const ad = toAdDate(from, calendar);
    if (!pool) return setError("Choose the pool or block.");
    if (!/^\d{1,3}(\.\d{1,6})?$/.test(rate.trim()) || Number(rate) > 100) return setError("The rate must be a percent between 0 and 100.");
    if (!ad) return setError(calendar === "BS" ? "Write the date in BS, for example 2082-04-01." : "Write the date as year-month-day.");
    setBusy(true);
    setError(null);
    try {
      await put({ pool, rate: rate.trim(), effective_from: ad, note: note.trim() });
      setRate("");
      setNote("");
      onChanged();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function applyPreset(index: number) {
    const ad = toAdDate(presetDate, calendar);
    if (!ad) return setError(calendar === "BS" ? "Write the date the rates start from in BS (2082-04-01) first." : "Write the date the rates start from first.");
    const preset = schedule.rate_presets[index];
    setBusy(true);
    setError(null);
    try {
      for (const [p, r] of Object.entries(preset.rates)) await put({ pool: p, rate: r, effective_from: ad, note: preset.name });
      onChanged();
    } catch (err) {
      setError(errorMessage(err));
      onChanged();
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: string) {
    setBusy(true);
    setError(null);
    try {
      await api(`companies/${companyId}/tax-depreciation/rates/${id}`, { method: "DELETE" });
      onChanged();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const show = (iso: string) => formatDate(iso);
  return (
    <Card>
      <CardHeader title="Rates" description="The standard rates, and this company's own rates from a date. A company's own rate replaces the standard one from its date; the schedule shows which was used." />
      <CardBody className="space-y-5">
        <TableWrap>
          <Table>
            <thead>
              <tr>
                <Th>Pool</Th>
                <Th align="right">Standard rate %</Th>
                <Th>From</Th>
              </tr>
            </thead>
            <tbody>
              {schedule.standard_rates.map((r) => (
                <tr key={r.pool}>
                  <Td className="font-medium">{r.pool}</Td>
                  <Td align="right">{r.rate}</Td>
                  <Td className="whitespace-nowrap">{show(r.effective_from)}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </TableWrap>
        {schedule.company_rates.length > 0 ? (
          <TableWrap>
            <Table>
              <thead>
                <tr>
                  <Th>This company's rate</Th>
                  <Th align="right">Rate %</Th>
                  <Th>From</Th>
                  <Th>Note</Th>
                  <Th />
                </tr>
              </thead>
              <tbody>
                {schedule.company_rates.map((r) => (
                  <tr key={r.id}>
                    <Td className="font-medium">{r.pool}</Td>
                    <Td align="right">{r.rate}</Td>
                    <Td className="whitespace-nowrap">{show(r.effective_from)}</Td>
                    <Td className="text-ink-soft">{r.note}</Td>
                    <Td align="right">
                      {schedule.can_edit ? (
                        <Button size="sm" variant="ghost" onClick={() => remove(r.id)} disabled={busy}>
                          Remove
                        </Button>
                      ) : null}
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </TableWrap>
        ) : (
          <p className="text-sm text-ink-soft">This company has no rates of its own: the standard rates are used.</p>
        )}
        {schedule.can_edit ? (
          <>
            <form onSubmit={save} className="grid gap-4 sm:grid-cols-4" noValidate>
              <Field label="Pool" htmlFor="rt-pool">
                <Select id="rt-pool" value={pool} onChange={(e) => setPool(e.target.value)}>
                  <option value="">Choose...</option>
                  {schedule.pool_choices.map((p) => (
                    <option key={p.code} value={p.code}>
                      {p.code}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="Rate %" htmlFor="rt-rate">
                <Input id="rt-rate" inputMode="decimal" value={rate} onChange={(e) => setRate(e.target.value)} />
              </Field>
              <Field label="From" htmlFor="rt-from" hint={dateHint} className="sm:col-span-2">
                <Input id="rt-from" value={from} onChange={(e) => setFrom(e.target.value)} placeholder={calendar === "BS" ? "2081-04-01" : "2025-04-01"} />
              </Field>
              <Field label="Note (optional)" htmlFor="rt-note" className="sm:col-span-3">
                <Input id="rt-note" value={note} onChange={(e) => setNote(e.target.value)} maxLength={300} />
              </Field>
              <div className="flex items-end">
                <Button type="submit" loading={busy}>
                  Save rate
                </Button>
              </div>
            </form>
            {schedule.rate_presets.length > 0 ? (
              <div className="space-y-2 rounded-md border border-rule bg-paper/50 p-4">
                <p className="text-sm font-medium text-ink">Start from a set of rates</p>
                <Field label="Rates start from" htmlFor="rt-preset-date" hint={dateHint} className="max-w-xs">
                  <Input id="rt-preset-date" value={presetDate} onChange={(e) => setPresetDate(e.target.value)} placeholder={calendar === "BS" ? "2081-04-01" : "2025-04-01"} />
                </Field>
                {schedule.rate_presets.map((p, i) => (
                  <div key={p.name} className="space-y-1">
                    <Button variant="secondary" size="sm" onClick={() => applyPreset(i)} disabled={busy}>
                      Use: {p.name}
                    </Button>
                    <p className="text-xs text-ink-faint">
                      {Object.entries(p.rates)
                        .map(([k, v]) => `${k} ${v}%`)
                        .join(", ")}
                      . {p.note}
                    </p>
                  </div>
                ))}
              </div>
            ) : null}
          </>
        ) : (
          <p className="text-xs text-ink-faint">Setting rates is for a senior accountant, CA or admin.</p>
        )}
        {error ? <Notice kind="error">{error}</Notice> : null}
      </CardBody>
    </Card>
  );
}