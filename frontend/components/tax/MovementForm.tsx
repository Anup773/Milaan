"use client";

import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Field, Input, Select } from "@/components/ui/form";
import { Notice } from "@/components/common/notice";
import { api, errorMessage } from "@/lib/api-client";
import { adToBs, isoBs } from "@/lib/bs-calendar";
import { parseAmountInput } from "@/lib/format";
import { toAdDate } from "@/lib/tax-dep-paste";
import type { MovementKind, Scheme, TaxMovement, TaxSchedule } from "@/lib/tax-dep-types";

interface DetailField {
  key: string;
  label: string;
  kind: "text" | "amount" | "bool" | "asset";
  hint?: string;
  required?: boolean;
}

/** The extra facts each country needs for each kind of entry. Mirrors what the engine accepts (tax_dep/service.py). */
export function detailFields(scheme: Scheme, kind: MovementKind, pool: string): DetailField[] {
  if (scheme === "NP") {
    const intangible = pool.toUpperCase().startsWith("E");
    if (kind === "DISPOSAL") return [{ key: "dissolves_pool", label: "Every asset in the pool was disposed of (the pool closes)", kind: "bool" }];
    const out: DetailField[] = [];
    if (intangible) out.push({ key: "life_years", label: "Useful life (years)", kind: "amount", required: true, hint: "Rounded to the nearest half year." });
    if (kind === "OPENING") {
      out.push({ key: "deferred", label: "Cost still to be added next year", kind: "amount", hint: "The part of last year's additions that counts this year." });
      if (intangible) out.push({ key: "accumulated", label: "Depreciation so far", kind: "amount" });
    }
    return out;
  }
  if (scheme === "IN") {
    return kind === "DISPOSAL" ? [{ key: "block_ceases", label: "Every asset in the block was sold (the block ceases)", kind: "bool" }] : [];
  }
  if (kind === "ADDITION") {
    return [
      { key: "asset_ref", label: "Asset reference", kind: "text", required: true, hint: "Your own tag or name. A sale refers to it." },
      { key: "section_179", label: "Section 179 expense", kind: "amount", hint: "Taken in the year it is placed in service. Milaan does not apply the Section 179 limits." },
      { key: "bonus_percent", label: "Bonus depreciation %", kind: "amount", hint: "Enter the percent that applies to this asset (0 to 100)." },
    ];
  }
  if (kind === "DISPOSAL") return [{ key: "asset_ref", label: "Asset sold", kind: "asset", required: true }];
  return [];
}

const KIND_LABEL: Record<Scheme, Record<MovementKind, string>> = {
  NP: { OPENING: "Opening balance", ADDITION: "Addition (cost)", DISPOSAL: "Disposal (proceeds)" },
  IN: { OPENING: "Opening written-down value", ADDITION: "Addition (cost)", DISPOSAL: "Sale (proceeds)" },
  US: { OPENING: "Opening balance", ADDITION: "Asset placed in service (cost)", DISPOSAL: "Sale of an asset (proceeds)" },
};

export function kindLabel(scheme: Scheme, kind: MovementKind): string {
  return KIND_LABEL[scheme][kind];
}

/** Adds or changes one input of the schedule. */
export function MovementForm({
  companyId,
  schedule,
  editing,
  onDone,
  onCancel,
}: {
  companyId: string;
  schedule: TaxSchedule;
  editing: TaxMovement | null;
  onDone: () => void;
  onCancel: () => void;
}) {
  const scheme = schedule.scheme;
  const calendar = schedule.calendar;
  const kinds: MovementKind[] = scheme === "US" ? ["ADDITION", "DISPOSAL"] : ["OPENING", "ADDITION", "DISPOSAL"];
  const [kind, setKind] = useState<MovementKind>(editing?.kind ?? "ADDITION");
  const [pool, setPool] = useState(editing?.pool ?? "");
  const [dateText, setDateText] = useState(() => {
    if (!editing) return "";
    if (calendar === "BS") {
      const b = adToBs(editing.event_date);
      return b ? isoBs(b) : editing.event_date;
    }
    return editing.event_date;
  });
  const [amount, setAmount] = useState(editing?.amount ?? "");
  const [description, setDescription] = useState(editing?.description ?? "");
  const [details, setDetails] = useState<Record<string, string | boolean>>(editing?.details ?? {});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const fields = detailFields(scheme, kind, pool);
  const adDate = dateText.trim() ? toAdDate(dateText, calendar) : null;
  const soldAssets = schedule.movements.filter((m) => m.kind === "ADDITION" && typeof m.details.asset_ref === "string");

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!pool) return setError("Choose the " + (scheme === "IN" ? "block." : scheme === "US" ? "class." : "pool."));
    if (!adDate) return setError(calendar === "BS" ? "Write the date in BS, for example 2082-04-01." : "Write the date as year-month-day, for example 2025-04-01.");
    const cleaned = parseAmountInput(amount);
    if (cleaned === null || cleaned.startsWith("-")) return setError("The amount must be a number of zero or more, such as 125000 or 125000.50.");
    const body: Record<string, unknown> = { kind, pool, event_date: adDate, amount: cleaned, description: description.trim(), details: {} as Record<string, unknown> };
    const out = body.details as Record<string, unknown>;
    for (const f of fields) {
      const v = details[f.key];
      if (f.kind === "bool") {
        if (v === true) out[f.key] = true;
        continue;
      }
      const text = typeof v === "string" ? v.trim().replace(/,/g, "") : "";
      if (text === "") {
        if (f.required) return setError(`${f.label} is required.`);
        continue;
      }
      if (f.kind === "amount" && !/^\d+(\.\d+)?$/.test(text)) return setError(`${f.label} must be a number.`);
      out[f.key] = text;
    }
    setBusy(true);
    setError(null);
    try {
      if (editing) await api(`companies/${companyId}/tax-depreciation/movements/${editing.id}`, { method: "PUT", body });
      else await api(`companies/${companyId}/tax-depreciation/movements`, { method: "POST", body });
      onDone();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const poolWord = scheme === "IN" ? "Block" : scheme === "US" ? "Recovery class" : "Pool";
  return (
    <form onSubmit={submit} className="space-y-4" noValidate>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="What happened" htmlFor="td-kind">
          <Select
            id="td-kind"
            value={kind}
            onChange={(e) => {
              setKind(e.target.value as MovementKind);
              setDetails({});
            }}
          >
            {kinds.map((k) => (
              <option key={k} value={k}>
                {kindLabel(scheme, k)}
              </option>
            ))}
          </Select>
        </Field>
        <Field label={poolWord} htmlFor="td-pool">
          <Select id="td-pool" value={pool} onChange={(e) => setPool(e.target.value)}>
            <option value="">Choose...</option>
            {schedule.pool_choices.map((p) => (
              <option key={p.code} value={p.code}>
                {p.code === p.name ? p.code : `${p.code}: ${p.name}`}
              </option>
            ))}
            {scheme === "NP" ? <option value={pool.startsWith("E-") ? pool : "E-"}>E-(name): another intangible...</option> : null}
          </Select>
        </Field>
        {scheme === "NP" && pool.startsWith("E-") ? (
          <Field label="Name of this intangible pool" htmlFor="td-pool-name" hint="Each intangible with its own life goes in its own pool, for example E-licence.">
            <Input id="td-pool-name" value={pool} onChange={(e) => setPool(e.target.value)} maxLength={40} />
          </Field>
        ) : null}
        <Field
          label={kind === "OPENING" ? "Date (first day of the fiscal year)" : "Date"}
          htmlFor="td-date"
          hint={
            calendar === "BS"
              ? adDate
                ? `BS date. That is ${adDate} in AD.`
                : "Write the date in BS, for example 2082-04-01."
              : "Year-month-day, for example 2025-04-01."
          }
        >
          <Input id="td-date" value={dateText} onChange={(e) => setDateText(e.target.value)} placeholder={calendar === "BS" ? "2082-04-01" : "2025-04-01"} />
        </Field>
        <Field label={kind === "OPENING" ? "Balance" : kind === "ADDITION" ? "Cost" : "Sale proceeds"} htmlFor="td-amount">
          <Input id="td-amount" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} />
        </Field>
        {fields.map((f) =>
          f.kind === "bool" ? (
            <label key={f.key} className="flex items-start gap-2 text-sm text-ink sm:col-span-2">
              <input type="checkbox" className="mt-0.5 h-4 w-4 accent-ledger" checked={details[f.key] === true} onChange={(e) => setDetails((d) => ({ ...d, [f.key]: e.target.checked }))} />
              {f.label}
            </label>
          ) : f.kind === "asset" ? (
            <Field key={f.key} label={f.label} htmlFor={`td-${f.key}`}>
              <Select id={`td-${f.key}`} value={String(details[f.key] ?? "")} onChange={(e) => setDetails((d) => ({ ...d, [f.key]: e.target.value }))}>
                <option value="">Choose...</option>
                {soldAssets.map((a) => (
                  <option key={a.id} value={String(a.details.asset_ref)}>
                    {String(a.details.asset_ref)} ({a.pool})
                  </option>
                ))}
              </Select>
            </Field>
          ) : (
            <Field key={f.key} label={f.label} htmlFor={`td-${f.key}`} hint={f.hint}>
              <Input id={`td-${f.key}`} value={String(details[f.key] ?? "")} onChange={(e) => setDetails((d) => ({ ...d, [f.key]: e.target.value }))} inputMode={f.kind === "amount" ? "decimal" : undefined} />
            </Field>
          ),
        )}
        <Field label="Description (optional)" htmlFor="td-desc" className="sm:col-span-2">
          <Input id="td-desc" value={description} onChange={(e) => setDescription(e.target.value)} maxLength={200} />
        </Field>
      </div>
      {error ? <Notice kind="error">{error}</Notice> : null}
      <div className="flex flex-wrap gap-2">
        <Button type="submit" loading={busy}>
          {editing ? "Save changes" : "Add"}
        </Button>
        <Button variant="secondary" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </form>
  );
}