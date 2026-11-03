"use client";

import Link from "next/link";
import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from "react";
import { PageHeader } from "@/components/common/page-header";
import { Gate } from "@/components/common/gate";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Badge, type Tone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Field, Input, Select, Textarea } from "@/components/ui/form";
import { Table, TableWrap, Td, Th } from "@/components/ui/table";
import { Loading, Notice } from "@/components/common/notice";
import { api, errorMessage } from "@/lib/api-client";
import { useApi } from "@/lib/use-api";
import { formatDate } from "@/lib/format";
import { can, CAN } from "@/lib/roles";
import { useWorkspace } from "@/lib/workspace";
import type { CountryProfile, FiscalYearCreated, FiscalYearPreview, GuideLine, PolicyField, PolicySaved, PolicyView } from "@/lib/policy-types";

/** What the form holds: everything as text, exactly as typed. */
interface Form {
  accounting_framework: string;
  jurisdiction: string;
  currency: string;
  calendar: string;
  date_order: string;
  number_grouping: string;
  fiscal_year_start_month: string;
  tax_regime: string;
  depreciation_method: string;
  depreciation_start: string;
  default_useful_life_months: string;
  capitalization_threshold: string;
  inventory_valuation_method: string;
  statement_rounding: string;
  review_min_amount: string;
  review_large_amount: string;
  reason: string;
}

function formFrom(view: PolicyView): Form {
  const p = view.policy;
  const d = view.defaults;
  return {
    accounting_framework: p?.accounting_framework ?? "",
    jurisdiction: p?.jurisdiction ?? "",
    currency: p?.currency ?? "",
    calendar: p?.calendar ?? d.calendar,
    date_order: p?.date_order ?? d.date_order,
    number_grouping: p?.number_grouping ?? d.number_grouping,
    fiscal_year_start_month: p ? String(p.fiscal_year_start_month) : "",
    tax_regime: p?.tax_regime ?? "",
    depreciation_method: p?.depreciation_method ?? d.depreciation_method,
    depreciation_start: p?.depreciation_start ?? d.depreciation_start,
    default_useful_life_months: p ? (p.default_useful_life_months === null ? "" : String(p.default_useful_life_months)) : "",
    capitalization_threshold: p?.capitalization_threshold ?? d.capitalization_threshold,
    inventory_valuation_method: p?.inventory_valuation_method ?? d.inventory_valuation_method,
    statement_rounding: p?.statement_rounding ?? d.statement_rounding,
    review_min_amount: p?.review_min_amount ?? d.review_min_amount,
    review_large_amount: p?.review_large_amount ?? d.review_large_amount,
    reason: "",
  };
}

const AMOUNT = /^\d{1,15}(\.\d{1,2})?$/;

/** Mirrors the engine's cross-field rules so a bad combination is caught before it is sent; the server checks again. */
function lifoAllowed(view: PolicyView, f: Pick<Form, "jurisdiction" | "accounting_framework">): boolean {
  return f.jurisdiction === "US" && view.options.lifo_frameworks.includes(f.accounting_framework);
}

function problems(view: PolicyView, f: Form): string[] {
  const out: string[] = [];
  if (!f.jurisdiction) out.push("Choose the country.");
  if (!f.accounting_framework) out.push("Choose an accounting framework.");
  if (!f.currency) out.push("Choose the currency.");
  if (!f.fiscal_year_start_month) out.push("Choose the month the fiscal year starts in.");
  if (!f.tax_regime) out.push("Choose the tax regime.");
  if (f.calendar === "BS" && f.jurisdiction !== "NP") out.push("The Bikram Sambat (BS) calendar is for Nepal only. Choose the AD calendar.");
  const only = view.options.framework_countries[f.accounting_framework];
  if (only && f.jurisdiction && only !== f.jurisdiction) {
    out.push(`${f.accounting_framework} belongs to ${view.options.countries.find((c) => c.value === only)?.label ?? only} only. Choose another framework for this country.`);
  }
  if (f.inventory_valuation_method === "LIFO" && !lifoAllowed(view, f)) out.push("LIFO is allowed only for a United States company under US GAAP (or local GAAP).");
  if (f.default_useful_life_months.trim() !== "" && !/^\d{1,4}$/.test(f.default_useful_life_months.trim())) out.push("The default useful life must be a whole number of months.");
  for (const [key, label] of [
    ["capitalization_threshold", "Capitalisation threshold"],
    ["review_min_amount", "Smallest entry to flag"],
    ["review_large_amount", "Large entry from"],
  ] as const) {
    if (!AMOUNT.test(f[key].trim())) out.push(`${label} must be an amount like 5000 or 5000.50.`);
  }
  if (AMOUNT.test(f.review_min_amount.trim()) && AMOUNT.test(f.review_large_amount.trim()) && Number(f.review_large_amount) < Number(f.review_min_amount)) {
    out.push("The large-entry amount cannot be smaller than the smallest entry to flag.");
  }
  if (view.configured && f.reason.trim() === "") out.push("Say why the policy is being changed.");
  return out;
}

function body(f: Form, configured: boolean) {
  const life = f.default_useful_life_months.trim();
  return {
    accounting_framework: f.accounting_framework,
    jurisdiction: f.jurisdiction,
    currency: f.currency,
    calendar: f.calendar,
    date_order: f.date_order,
    number_grouping: f.number_grouping,
    fiscal_year_start_month: Number(f.fiscal_year_start_month),
    tax_regime: f.tax_regime,
    depreciation_method: f.depreciation_method,
    depreciation_start: f.depreciation_start,
    default_useful_life_months: life === "" ? null : Number(life),
    capitalization_threshold: f.capitalization_threshold.trim(),
    inventory_valuation_method: f.inventory_valuation_method,
    statement_rounding: f.statement_rounding,
    review_min_amount: f.review_min_amount.trim(),
    review_large_amount: f.review_large_amount.trim(),
    ...(configured ? { reason: f.reason.trim() } : {}),
  };
}

/** One labelled field with the plain statement of what reads this setting. */
function Setting({ id, field, view, children, className }: { id: string; field: PolicyField; view: PolicyView; children: ReactNode; className?: string }) {
  return (
    <Field label={view.labels[field]} htmlFor={id} hint={view.used_by[field]} className={className}>
      {children}
    </Field>
  );
}

const GUIDE_TONE: Record<GuideLine["status"], { tone: Tone; label: string }> = {
  built: { tone: "pass", label: "Built" },
  partial: { tone: "warn", label: "Partly built" },
  not_built: { tone: "neutral", label: "Not built yet" },
};

/** What Milaan does for the chosen country today, topic by topic. Choosing a country never switches on rules that are not there. */
function CountryGuide({ profile }: { profile: CountryProfile }) {
  return (
    <Card>
      <CardHeader
        title={`What Milaan does for ${profile.name}`}
        description={
          profile.support === "full"
            ? "Your country's calendar, dates, tax depreciation and statement titles are built in. The list below says exactly what is and is not covered."
            : "Only sensible defaults are built for this country. Everything else (imports, ledger, adjustments, approvals, the audit trail, reconciliation) works the same as anywhere."
        }
      />
      <CardBody className="space-y-3">
        {profile.fiscal_year_note ? <p className="text-sm text-ink-soft">{profile.fiscal_year_note}</p> : null}
        <ul className="divide-y divide-rule/70">
          {profile.guide.map((g) => (
            <li key={g.topic} className="space-y-1 py-3 first:pt-0 last:pb-0">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-sm font-medium text-ink">{g.topic}</span>
                <Badge tone={GUIDE_TONE[g.status].tone}>{GUIDE_TONE[g.status].label}</Badge>
              </div>
              <p className="text-sm text-ink-soft">{g.text}</p>
            </li>
          ))}
        </ul>
        <p className="text-xs text-ink-faint">Rates and rules were taken from public sources. Confirm them with your CA before you file anything.</p>
      </CardBody>
    </Card>
  );
}

function PolicyForm({ companyId, companyName, view, reload }: { companyId: string; companyName: string; view: PolicyView; reload: () => void }) {
  const { reloadPolicy } = useWorkspace();
  const [form, setForm] = useState<Form>(() => formFrom(view));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [filled, setFilled] = useState<string | null>(null);
  const [shown, setShown] = useState<string[]>([]);

  // After a save the server's copy is the truth; show it.
  useEffect(() => {
    setForm(formFrom(view));
  }, [view]);

  const set = (key: keyof Form) => (e: { target: { value: string } }) => {
    setForm((f) => ({ ...f, [key]: e.target.value }));
    setSaved(null);
    setFilled(null);
  };
  const canEdit = view.can_edit;
  const locked = view.depreciation_posted;
  const o = view.options;
  const dirty = JSON.stringify({ ...formFrom(view), reason: "" }) !== JSON.stringify({ ...form, reason: "" });
  const profile = useMemo(() => o.country_profiles.find((p) => p.code === form.jurisdiction) ?? null, [o.country_profiles, form.jurisdiction]);
  const fullCountries = o.country_profiles.filter((p) => p.support === "full");

  /** "I am a company in <country>": fills in the usual choices. Nothing is saved until the form is saved. */
  function applyCountry(code: string) {
    const p = o.country_profiles.find((c) => c.code === code);
    if (!p) return;
    const s = p.suggested;
    setForm((f) => ({
      ...f,
      jurisdiction: s.jurisdiction,
      accounting_framework: s.accounting_framework,
      currency: s.currency,
      calendar: s.calendar,
      date_order: s.date_order,
      number_grouping: s.number_grouping,
      fiscal_year_start_month: String(s.fiscal_year_start_month),
      tax_regime: s.tax_regime,
      inventory_valuation_method: s.inventory_valuation_method,
      statement_rounding: s.statement_rounding,
    }));
    setSaved(null);
    setFilled(`Filled in the usual choices for ${p.name}. Look them over, change what differs for this company, then save.`);
  }

  // Choices the engine would refuse are not offered.
  const frameworks = o.accounting_frameworks.filter((fw) => {
    const only = o.framework_countries[fw];
    return !only || !form.jurisdiction || only === form.jurisdiction || fw === form.accounting_framework;
  });
  const calendars = o.calendars.filter((c) => (profile ? profile.calendar_choices.includes(c.value) : c.value === "AD") || c.value === form.calendar);
  const taxRegimes = o.tax_regimes.filter((t) => !profile || profile.tax_regime_choices.includes(t.value) || t.value === form.tax_regime);
  const inventory = o.inventory_methods.filter((m) => m.value !== "LIFO" || lifoAllowed(view, form) || form.inventory_valuation_method === "LIFO");

  async function save(event: FormEvent) {
    event.preventDefault();
    const found = problems(view, form);
    setShown(found);
    if (found.length > 0) return;
    setSaving(true);
    setError(null);
    setSaved(null);
    try {
      const result = await api<PolicySaved>(`companies/${companyId}/policy`, { method: "PUT", body: body(form, view.configured) });
      setSaved(
        result.changed.length === 0
          ? "Nothing changed."
          : view.configured
            ? `Saved. Changed: ${result.changed.map((f) => result.labels[f].toLowerCase()).join(", ")}.`
            : "The accounting policy is set up.",
      );
      setFilled(null);
      reload();
      reloadPolicy();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-5">
      <form onSubmit={save} className="space-y-5" noValidate>
        {!view.configured ? (
          <Notice kind="info">
            {companyName} has no accounting policy yet. Until you set one up, Milaan uses its built-in defaults for depreciation and transaction review, shows dates in AD, and lists no rule sets
            for this company. Start by choosing the country below.
          </Notice>
        ) : null}
        {!canEdit ? (
          <Notice kind="info">
            You can read the policy but not change it. {view.configured ? "Changing it" : "Setting it up"} is for these roles:{" "}
            {(view.configured ? view.who_may.change : view.who_may.set_up).join(", ").replace(/_/g, " ")}.
          </Notice>
        ) : null}

        <Card>
          <CardHeader
            title="Where is this company?"
            description="Everything else in Milaan works the same everywhere. The country decides how dates and numbers are written, the fiscal year, the statement titles, the tax depreciation rules and which choices are offered."
          />
          <CardBody className="space-y-4">
            {canEdit ? (
              <div className="flex flex-wrap gap-2" role="group" aria-label="Quick country choice">
                {fullCountries.map((p) => (
                  <Button key={p.code} variant={form.jurisdiction === p.code ? "primary" : "secondary"} onClick={() => applyCountry(p.code)}>
                    {p.name}
                  </Button>
                ))}
              </div>
            ) : null}
            <div className="grid gap-4 sm:grid-cols-2">
              <Setting id="pol-country" field="jurisdiction" view={view}>
                <Select id="pol-country" value={form.jurisdiction} onChange={(e) => (e.target.value ? applyCountry(e.target.value) : set("jurisdiction")(e))} disabled={!canEdit}>
                  <option value="">Choose...</option>
                  {o.countries.map((c) => (
                    <option key={c.value} value={c.value}>
                      {c.label}
                    </option>
                  ))}
                </Select>
              </Setting>
            </div>
            {filled ? <Notice kind="info">{filled}</Notice> : null}
            {view.configured && dirty && form.jurisdiction !== view.policy?.jurisdiction ? (
              <Notice kind="warning">
                Changing the country changes how every date in this company is read and shown. Dates already stored do not change, but a file imported afterwards is read the new way.
              </Notice>
            ) : null}
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="The company" description="Who this company is. These decide which rule sets are listed for it." />
          <CardBody className="grid gap-4 sm:grid-cols-2">
            <Setting id="pol-framework" field="accounting_framework" view={view}>
              <Select id="pol-framework" value={form.accounting_framework} onChange={set("accounting_framework")} disabled={!canEdit}>
                <option value="">Choose...</option>
                {frameworks.map((f) => (
                  <option key={f} value={f}>
                    {f}
                  </option>
                ))}
              </Select>
            </Setting>
            <Setting id="pol-currency" field="currency" view={view}>
              <Select id="pol-currency" value={form.currency} onChange={set("currency")} disabled={!canEdit}>
                <option value="">Choose...</option>
                {o.currencies.map((c) => (
                  <option key={c.value} value={c.value}>
                    {c.label}
                  </option>
                ))}
              </Select>
            </Setting>
            <Setting id="pol-tax" field="tax_regime" view={view}>
              <Select id="pol-tax" value={form.tax_regime} onChange={set("tax_regime")} disabled={!canEdit}>
                <option value="">Choose...</option>
                {taxRegimes.map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.label}
                  </option>
                ))}
              </Select>
            </Setting>
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="Dates, fiscal year and numbers" description="How this company writes dates and amounts. Files are read with these settings, and a date that does not fit is refused with a reason, never guessed." />
          <CardBody className="grid gap-4 sm:grid-cols-2">
            <Setting id="pol-calendar" field="calendar" view={view}>
              <Select id="pol-calendar" value={form.calendar} onChange={set("calendar")} disabled={!canEdit}>
                {calendars.map((c) => (
                  <option key={c.value} value={c.value}>
                    {c.label}
                  </option>
                ))}
              </Select>
            </Setting>
            <Setting id="pol-order" field="date_order" view={view}>
              <Select id="pol-order" value={form.date_order} onChange={set("date_order")} disabled={!canEdit}>
                {o.date_orders.map((c) => (
                  <option key={c.value} value={c.value}>
                    {c.label}
                  </option>
                ))}
              </Select>
            </Setting>
            <Setting id="pol-month" field="fiscal_year_start_month" view={view}>
              <Select id="pol-month" value={form.fiscal_year_start_month} onChange={set("fiscal_year_start_month")} disabled={!canEdit}>
                <option value="">Choose...</option>
                {(form.calendar === "BS" ? BS_MONTHS : o.months).map((m) => (
                  <option key={m.value} value={m.value}>
                    {m.label}
                  </option>
                ))}
              </Select>
            </Setting>
            <Setting id="pol-grouping" field="number_grouping" view={view}>
              <Select id="pol-grouping" value={form.number_grouping} onChange={set("number_grouping")} disabled={!canEdit}>
                {o.number_groupings.map((c) => (
                  <option key={c.value} value={c.value}>
                    {c.label}
                  </option>
                ))}
              </Select>
            </Setting>
            <Setting id="pol-rounding" field="statement_rounding" view={view}>
              <Select id="pol-rounding" value={form.statement_rounding} onChange={set("statement_rounding")} disabled={!canEdit}>
                {o.roundings.map((c) => (
                  <option key={c.value} value={c.value}>
                    {c.label}
                  </option>
                ))}
              </Select>
            </Setting>
          </CardBody>
          {form.calendar === "BS" ? (
            <CardBody className="border-t border-rule pt-4">
              <Notice kind="warning">
                BS month lengths are checked against four public sources up to BS 2083. Later years are provisional and may be a day out in some months; Milaan warns whenever it uses one.
                Dates are stored as AD and shown in BS. The date pickers on some pages still use AD.
              </Notice>
            </CardBody>
          ) : null}
        </Card>

        <Card>
          <CardHeader title="Depreciation" description="How fixed assets are depreciated in the books and when they are capitalised. Tax depreciation has its own page." />
          <CardBody className="space-y-4">
            {locked ? (
              <Notice kind="warning">
                Depreciation has already been posted for this company, so the method and the starting rule are locked: changing them would make the posted figures disagree with the
                policy. The other settings can still be changed.
              </Notice>
            ) : null}
            <div className="grid gap-4 sm:grid-cols-2">
              <Setting id="pol-dep-method" field="depreciation_method" view={view}>
                <Select id="pol-dep-method" value={form.depreciation_method} onChange={set("depreciation_method")} disabled={!canEdit || locked}>
                  {o.depreciation_methods.map((m) => (
                    <option key={m.value} value={m.value}>
                      {m.label}
                    </option>
                  ))}
                </Select>
              </Setting>
              <Setting id="pol-dep-start" field="depreciation_start" view={view}>
                <Select id="pol-dep-start" value={form.depreciation_start} onChange={set("depreciation_start")} disabled={!canEdit || locked}>
                  {o.depreciation_starts.map((m) => (
                    <option key={m.value} value={m.value}>
                      {m.label}
                    </option>
                  ))}
                </Select>
              </Setting>
              <Setting id="pol-life" field="default_useful_life_months" view={view}>
                <Input id="pol-life" inputMode="numeric" value={form.default_useful_life_months} onChange={set("default_useful_life_months")} placeholder="None" disabled={!canEdit} />
              </Setting>
              <Setting id="pol-cap" field="capitalization_threshold" view={view}>
                <Input id="pol-cap" inputMode="decimal" value={form.capitalization_threshold} onChange={set("capitalization_threshold")} disabled={!canEdit} />
              </Setting>
            </div>
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="Inventory" description="How the cost of inventory is worked out." />
          <CardBody className="grid gap-4 sm:grid-cols-2">
            <Setting id="pol-inv" field="inventory_valuation_method" view={view}>
              <Select id="pol-inv" value={form.inventory_valuation_method} onChange={set("inventory_valuation_method")} disabled={!canEdit}>
                {inventory.map((m) => (
                  <option key={m.value} value={m.value}>
                    {m.label}
                  </option>
                ))}
              </Select>
            </Setting>
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="Transaction review" description="Which entries the exception checks look at. Amounts are in the company's own currency." />
          <CardBody className="grid gap-4 sm:grid-cols-2">
            <Setting id="pol-min" field="review_min_amount" view={view}>
              <Input id="pol-min" inputMode="decimal" value={form.review_min_amount} onChange={set("review_min_amount")} disabled={!canEdit} />
            </Setting>
            <Setting id="pol-large" field="review_large_amount" view={view}>
              <Input id="pol-large" inputMode="decimal" value={form.review_large_amount} onChange={set("review_large_amount")} disabled={!canEdit} />
            </Setting>
          </CardBody>
        </Card>

        {canEdit ? (
          <Card>
            <CardBody className="space-y-4">
              {view.configured ? (
                <Field label="Why is the policy being changed?" htmlFor="pol-reason" hint="Kept in the audit trail with the old and new values.">
                  <Textarea id="pol-reason" rows={2} value={form.reason} onChange={set("reason")} maxLength={500} />
                </Field>
              ) : null}
              {shown.length > 0 ? (
                <Notice kind="error">
                  <ul className="list-disc space-y-0.5 pl-5">
                    {shown.map((p) => (
                      <li key={p}>{p}</li>
                    ))}
                  </ul>
                </Notice>
              ) : null}
              {error ? <Notice kind="error">{error}</Notice> : null}
              {saved ? <Notice kind="success">{saved}</Notice> : null}
              <div className="flex flex-wrap items-center gap-3">
                <Button type="submit" loading={saving} disabled={view.configured && !dirty}>
                  {view.configured ? "Save changes" : "Set up policy"}
                </Button>
                {view.configured && !dirty ? <span className="text-xs text-ink-faint">Nothing to save yet.</span> : null}
                {view.policy ? (
                  <span className="text-xs text-ink-faint">
                    Last saved {new Date(view.policy.updated_at).toLocaleString()}
                    {view.policy.change_reason ? `: ${view.policy.change_reason}` : ""}
                  </span>
                ) : null}
              </div>
            </CardBody>
          </Card>
        ) : null}
      </form>

      {profile ? <CountryGuide profile={profile} /> : null}

      {view.configured && view.policy ? <FiscalYearCard companyId={companyId} calendarLabel={view.policy.calendar} /> : null}

      <Card>
        <CardHeader
          title="Rule sets that apply"
          description="From the Rules catalog, for this company's framework, country and tax regime. Most are catalog only: Milaan does not check against them yet."
          actions={
            <Link href="/rules" className="text-sm font-medium text-ledger underline">
              Open the Rules catalog
            </Link>
          }
        />
        <CardBody>
          {view.rule_sets.length === 0 ? (
            <p className="text-sm text-ink-soft">{view.configured ? "No rule sets match this policy." : "Set up the policy to see the rule sets that apply."}</p>
          ) : (
            <ul className="divide-y divide-rule/70">
              {view.rule_sets.map((r) => (
                <li key={r.id} className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
                  <span className="text-ink">
                    {r.title} <span className="text-ink-faint">({r.family})</span>
                  </span>
                  <Badge tone={r.status === "ACTIVE" ? "pass" : "neutral"}>{r.status === "ACTIVE" ? "Active in Milaan" : "Catalog only"}</Badge>
                </li>
              ))}
            </ul>
          )}
        </CardBody>
      </Card>
    </div>
  );
}

/** The months of a BS year, for a company that keeps its books in Bikram Sambat (month 4, Shrawan, starts Nepal's fiscal year). */
const BS_MONTHS = ["Baisakh", "Jestha", "Ashadh", "Shrawan", "Bhadra", "Ashwin", "Kartik", "Mangsir", "Poush", "Magh", "Falgun", "Chaitra"].map((label, i) => ({
  value: i + 1,
  label,
}));

/** Today as YYYY-MM-DD in the viewer's own calendar day, moved by whole years (29 February becomes the 28th). */
function dayInYears(offset: number): string {
  const now = new Date();
  const year = now.getFullYear() + offset;
  const month = now.getMonth() + 1;
  const day = month === 2 && now.getDate() === 29 ? 28 : now.getDate();
  return `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

/** Works out a fiscal year from the company's calendar and start month, and creates its periods. */
function FiscalYearCard({ companyId, calendarLabel }: { companyId: string; calendarLabel: string }) {
  const { me, reloadPeriods } = useWorkspace();
  const [which, setWhich] = useState("0");
  const [split, setSplit] = useState<"MONTHLY" | "YEARLY">("MONTHLY");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const date = dayInYears(Number(which));
  const { data, error: loadError, loading, reload } = useApi<FiscalYearPreview>(`companies/${companyId}/fiscal-year`, { date, split });
  const mayCreate = can(me?.role, CAN.createPeriod);

  async function create() {
    setCreating(true);
    setError(null);
    setDone(null);
    try {
      const result = await api<FiscalYearCreated>(`companies/${companyId}/fiscal-year`, { method: "POST", body: { date, split } });
      setDone(`Created ${result.created} period${result.created === 1 ? "" : "s"} for ${result.fiscal_year.label}.`);
      reload();
      await reloadPeriods();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setCreating(false);
    }
  }

  return (
    <Card>
      <CardHeader
        title="Fiscal year and periods"
        description={`Works out the exact dates of a fiscal year from this company's ${calendarLabel === "BS" ? "Bikram Sambat calendar" : "calendar"} and fiscal year start, and creates its accounting periods in one go.`}
      />
      <CardBody className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Which year" htmlFor="fy-which">
            <Select id="fy-which" value={which} onChange={(e) => setWhich(e.target.value)}>
              <option value="-1">The previous fiscal year</option>
              <option value="0">The current fiscal year</option>
              <option value="1">The next fiscal year</option>
            </Select>
          </Field>
          <Field label="Periods" htmlFor="fy-split">
            <Select id="fy-split" value={split} onChange={(e) => setSplit(e.target.value as "MONTHLY" | "YEARLY")}>
              <option value="MONTHLY">Twelve monthly periods</option>
              <option value="YEARLY">One period for the whole year</option>
            </Select>
          </Field>
        </div>
        {loadError ? <Notice kind="error">{loadError}</Notice> : null}
        {loading && !data ? <Loading /> : null}
        {data ? (
          <>
            <p className="text-sm text-ink">
              Fiscal year <span className="font-semibold">{data.fiscal_year.label}</span>: {formatDate(data.fiscal_year.start)} to {formatDate(data.fiscal_year.end)}
            </p>
            {data.warnings.map((w) => (
              <Notice key={w} kind="warning">
                {w}
              </Notice>
            ))}
            {data.clashes.length > 0 ? (
              <Notice kind="info">
                These dates overlap periods the company already has ({data.clashes.slice(0, 3).map((c) => `${c.new} and ${c.existing}`).join("; ")}
                {data.clashes.length > 3 ? ", ..." : ""}), so they cannot be created again.
              </Notice>
            ) : null}
            <TableWrap>
              <Table>
                <thead>
                  <tr>
                    <Th>Period</Th>
                    <Th>From</Th>
                    <Th>To</Th>
                  </tr>
                </thead>
                <tbody>
                  {data.periods.map((p) => (
                    <tr key={p.label}>
                      <Td className="font-medium">{p.label}</Td>
                      <Td className="whitespace-nowrap">{formatDate(p.start)}</Td>
                      <Td className="whitespace-nowrap">{formatDate(p.end)}</Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            </TableWrap>
          </>
        ) : null}
        {error ? <Notice kind="error">{error}</Notice> : null}
        {done ? <Notice kind="success">{done}</Notice> : null}
        {mayCreate ? (
          <Button onClick={create} loading={creating} disabled={!data || !data.can_create}>
            Create these periods
          </Button>
        ) : (
          <p className="text-xs text-ink-faint">Creating periods is for a senior accountant, CA or admin.</p>
        )}
      </CardBody>
    </Card>
  );
}

function PolicyLoader({ companyId, companyName }: { companyId: string; companyName: string }) {
  const { data, error, loading, reload } = useApi<PolicyView>(`companies/${companyId}/policy`);
  if (error) return <Notice kind="error">{error}</Notice>;
  if (loading && !data) return <Loading />;
  if (!data) return null;
  return <PolicyForm key={companyId} companyId={companyId} companyName={companyName} view={data} reload={reload} />;
}

export default function PolicyPage() {
  return (
    <>
      <PageHeader
        title="Accounting policy"
        description="Start with the country. It decides how dates and numbers are written, the fiscal year, statement titles and tax depreciation. Below that sit the framework, depreciation, inventory and review thresholds. Every change is kept in the audit trail."
      />
      <Gate>{({ company }) => <PolicyLoader companyId={company.id} companyName={company.name} />}</Gate>
    </>
  );
}