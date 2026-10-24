"use client";

import { useState } from "react";
import { PageHeader } from "@/components/common/page-header";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Field, Select } from "@/components/ui/form";
import { Tabs } from "@/components/ui/tabs";
import { Empty, Loading, Notice } from "@/components/common/notice";
import { useApi } from "@/lib/use-api";
import type { Coverage, RuleFamily, RuleItem, RuleSet, RulesCatalog } from "@/lib/rules-types";

const COVERAGE_LABEL: Record<Coverage, string> = { FULL: "Covered by Milaan", PARTIAL: "Partly covered", NONE: "Not covered yet" };
const COVERAGE_TONE: Record<Coverage, "pass" | "warn" | "neutral"> = { FULL: "pass", PARTIAL: "warn", NONE: "neutral" };
const KIND_LABEL: Record<string, string> = { reconciliation: "Reconciliation check", exception: "Review flag", feature: "Built-in control" };

const COUNTRY: Record<string, string> = { INTL: "All countries", IN: "India", NP: "Nepal", GB: "United Kingdom", AE: "United Arab Emirates" };
const countryName = (code: string) => COUNTRY[code] ?? code;

function Item({ item }: { item: RuleItem }) {
  return (
    <li className="px-5 py-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="text-sm font-medium text-ink">
            {item.title}
            {item.reference ? <span className="ml-2 font-normal text-ink-faint">{item.reference}</span> : null}
          </div>
          <div className="mt-0.5 text-sm text-ink-soft">{item.description}</div>
        </div>
        <Badge tone={COVERAGE_TONE[item.coverage]}>{COVERAGE_LABEL[item.coverage]}</Badge>
      </div>
      {item.checks.length > 0 ? (
        <div className="mt-2 text-xs text-ink-soft">
          <span className="mr-1.5 font-medium">Related:</span>
          {item.checks.map((c, i) => (
            <span key={`${c.kind}:${c.id}`}>
              {c.title ?? c.id} <span className="text-ink-faint">({KIND_LABEL[c.kind] ?? c.kind})</span>
              {i < item.checks.length - 1 ? "; " : ""}
            </span>
          ))}
        </div>
      ) : null}
      {item.note ? <div className="mt-1.5 text-xs text-ink-faint">What is not covered: {item.note}</div> : null}
    </li>
  );
}

function RuleSetCard({ set }: { set: RuleSet }) {
  const active = set.status === "ACTIVE";
  return (
    <Card>
      <CardHeader
        title={set.title}
        description={set.description}
        actions={
          <>
            <Badge tone={active ? "pass" : "neutral"}>{active ? "Active in Milaan" : "Catalog only"}</Badge>
            <Badge tone="info">{countryName(set.jurisdiction)}</Badge>
            <Badge>{set.framework === "ANY" ? "Any framework" : set.framework}</Badge>
          </>
        }
      />
      <CardBody className="p-0">
        <details open={active}>
          <summary className="cursor-pointer select-none px-5 py-2.5 text-sm text-ledger-dark hover:bg-paper">
            {set.items.length} {set.items.length === 1 ? "requirement" : "requirements"} · {set.coverage.FULL + set.coverage.PARTIAL} with a related check
            <span className="ml-2 text-xs text-ink-faint">Source: {set.authority}</span>
          </summary>
          <ul className="divide-y divide-rule/70 border-t border-rule/70">
            {set.items.map((it) => (
              <Item key={it.id} item={it} />
            ))}
          </ul>
        </details>
      </CardBody>
    </Card>
  );
}

const ALL = "all";
type FamilyTab = RuleFamily | typeof ALL;

export default function RulesPage() {
  const [jurisdiction, setJurisdiction] = useState("");
  const [framework, setFramework] = useState("");
  const [family, setFamily] = useState<FamilyTab>(ALL);
  const { data, error, loading } = useApi<RulesCatalog>("rules", { jurisdiction: jurisdiction || undefined, framework: framework || undefined });

  const sets = data ? data.rule_sets.filter((s) => family === ALL || s.family === family) : [];
  const tabs = data
    ? [
        { id: ALL as FamilyTab, label: "All", count: data.rule_sets.length },
        ...data.families.map((f) => ({ id: f.id as FamilyTab, label: f.title, count: data.rule_sets.filter((s) => s.family === f.id).length })),
      ]
    : [];
  const familyInfo = data && family !== ALL ? data.families.find((f) => f.id === family) : null;

  return (
    <>
      <PageHeader
        title="Rules"
        description="The accounting, auditing, tax and compliance rule sets Milaan knows about, and which of them it checks today."
      />
      {error ? <Notice kind="error">{error}</Notice> : null}
      {loading && !data ? <Loading /> : null}
      {data ? (
        <div className="space-y-5">
          <Notice kind="info">{data.notice}</Notice>

          <div className="flex flex-wrap items-end gap-4">
            <Field label="Country" htmlFor="rules-country">
              <Select id="rules-country" value={jurisdiction} onChange={(e) => setJurisdiction(e.target.value)}>
                <option value="">Any country</option>
                {data.filters.jurisdictions
                  .filter((j) => j !== "INTL")
                  .map((j) => (
                    <option key={j} value={j}>
                      {countryName(j)}
                    </option>
                  ))}
              </Select>
            </Field>
            <Field label="Framework" htmlFor="rules-framework">
              <Select id="rules-framework" value={framework} onChange={(e) => setFramework(e.target.value)}>
                <option value="">Any framework</option>
                {data.filters.frameworks
                  .filter((f) => f !== "ANY")
                  .map((f) => (
                    <option key={f} value={f}>
                      {f}
                    </option>
                  ))}
              </Select>
            </Field>
            <p className="pb-2 text-sm text-ink-soft" aria-live="polite">
              {data.summary.rule_sets} rule {data.summary.rule_sets === 1 ? "set" : "sets"}: {data.summary.active} active, {data.summary.catalog_only} catalog only.{" "}
              {data.summary.items_with_checks} of {data.summary.items} requirements have a related check.
            </p>
          </div>

          {jurisdiction || framework ? (
            <p className="text-xs text-ink-faint">Rule sets that apply to every country or under any framework are always included.</p>
          ) : null}

          <Tabs tabs={tabs} value={family} onChange={setFamily} />
          {familyInfo ? <p className="text-sm text-ink-soft">{familyInfo.description}</p> : null}

          {sets.length === 0 ? (
            <Empty title="No rule sets match">Try another country or framework.</Empty>
          ) : (
            <div className="space-y-4">
              {sets.map((s) => (
                <RuleSetCard key={s.id} set={s} />
              ))}
            </div>
          )}
        </div>
      ) : null}
    </>
  );
}
