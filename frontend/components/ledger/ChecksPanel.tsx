"use client";

import { useState, type FormEvent } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/form";
import { Table, TableWrap, Td, Th } from "@/components/ui/table";
import { Loading, Notice } from "@/components/common/notice";
import { Money } from "@/components/common/money";
import { api, errorMessage } from "@/lib/api-client";
import { useApi } from "@/lib/use-api";
import { useWorkspace } from "@/lib/workspace";
import { PRINTED_FIGURES, type PrintedComparison, type StatementChecks } from "@/lib/types";

/** Do the statements agree with each other, and with a signed statement? */
export function ChecksPanel({ companyId, periodId }: { companyId: string; periodId: string }) {
  return (
    <div className="space-y-4">
      <TiesCard companyId={companyId} periodId={periodId} />
      <PrintedCard companyId={companyId} periodId={periodId} />
    </div>
  );
}

function TiesCard({ companyId, periodId }: { companyId: string; periodId: string }) {
  const { locale } = useWorkspace();
  const { data, error, loading } = useApi<StatementChecks>(`companies/${companyId}/statements/checks`, { periodId });
  return (
    <Card>
      <CardHeader
        title="Do the statements agree with each other?"
        description={
          locale.rounding === "WHOLE"
            ? "Checked against each other for this period. This company's statements are in whole units, so figures that differ by up to 1 count as agreeing."
            : "Checked against each other for this period. This company keeps exact amounts, so figures must agree to the paisa or cent."
        }
        actions={data ? <Badge tone={data.all_pass ? "pass" : "fail"}>{data.all_pass ? "All agree" : `${data.errors} to look at`}</Badge> : null}
      />
      {error ? (
        <div className="p-5">
          <Notice kind="error">{error}</Notice>
        </div>
      ) : null}
      {loading && !data ? <Loading /> : null}
      {data ? (
        <ul className="divide-y divide-rule/70">
          {data.checks.map((c) => (
            <li key={c.id} className="flex flex-wrap items-start justify-between gap-2 px-5 py-3">
              <div className="min-w-0 max-w-2xl">
                <p className="text-sm font-medium text-ink">{c.title}</p>
                <p className="mt-0.5 text-sm text-ink-soft">{c.message}</p>
              </div>
              <Badge tone={c.status === "PASS" ? "pass" : c.status === "WARNING" ? "warn" : "fail"}>{c.status === "PASS" ? "Agrees" : c.status === "WARNING" ? "Look at" : "Does not agree"}</Badge>
            </li>
          ))}
        </ul>
      ) : null}
    </Card>
  );
}

function PrintedCard({ companyId, periodId }: { companyId: string; periodId: string }) {
  const [values, setValues] = useState<Record<string, string>>({});
  const [result, setResult] = useState<PrintedComparison | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function compare(event: FormEvent) {
    event.preventDefault();
    const figures: Record<string, string> = {};
    for (const [key, raw] of Object.entries(values)) if (raw.trim() !== "") figures[key] = raw.trim();
    if (Object.keys(figures).length === 0) {
      setError("Type at least one figure from the printed statement.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      setResult(await api<PrintedComparison>(`companies/${companyId}/statements/compare`, { method: "POST", body: { periodId, figures } }));
    } catch (err) {
      setResult(null);
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader
        title="Compare with a printed statement"
        description="Type the figures from a signed or audited statement and see whether the ledger gives the same numbers. Nothing is saved."
      />
      <CardBody>
        <form onSubmit={compare} className="space-y-4" noValidate>
          <div className="grid gap-3 sm:grid-cols-2">
            {PRINTED_FIGURES.map((f) => (
              <label key={f.key} className="block space-y-1">
                <span className="block text-sm font-medium text-ink">{f.label}</span>
                <Input
                  inputMode="decimal"
                  placeholder="As printed, for example 6,25,73,702"
                  value={values[f.key] ?? ""}
                  onChange={(e) => {
                    setValues((v) => ({ ...v, [f.key]: e.target.value }));
                    setResult(null);
                  }}
                />
              </label>
            ))}
          </div>
          {error ? <Notice kind="error">{error}</Notice> : null}
          <Button type="submit" loading={busy}>
            Compare
          </Button>
        </form>
      </CardBody>
      {result ? (
        <div className="border-t border-rule">
          <div className="flex flex-wrap items-center justify-between gap-2 px-5 py-3">
            <p className="text-sm text-ink-soft">
              {result.rounding === "WHOLE"
                ? "This company's statements are in whole units, so a difference of up to 1 counts as agreeing."
                : "This company keeps exact amounts, so a difference of any size is flagged."}
            </p>
            <Badge tone={result.all_agree ? "pass" : "fail"}>{result.all_agree ? "Everything typed agrees" : "Something differs"}</Badge>
          </div>
          <TableWrap>
            <Table>
              <thead>
                <tr>
                  <Th>Figure</Th>
                  <Th align="right">Printed</Th>
                  <Th align="right">Ledger</Th>
                  <Th align="right">Difference</Th>
                  <Th>Result</Th>
                </tr>
              </thead>
              <tbody>
                {result.rows.map((r) => (
                  <tr key={r.key}>
                    <Td>{r.label}</Td>
                    <Td align="right">
                      <Money value={r.printed} />
                    </Td>
                    <Td align="right">
                      <Money value={r.ledger} />
                    </Td>
                    <Td align="right">
                      <Money value={r.difference} />
                    </Td>
                    <Td>
                      <Badge tone={r.agrees ? "pass" : "fail"}>{r.agrees ? "Agrees" : "Differs"}</Badge>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </TableWrap>
        </div>
      ) : null}
    </Card>
  );
}