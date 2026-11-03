"use client";

import { Badge } from "@/components/ui/badge";
import { Card, CardHeader } from "@/components/ui/card";
import { Table, TableWrap, Td, Th } from "@/components/ui/table";
import { Loading, Notice } from "@/components/common/notice";
import { Money } from "@/components/common/money";
import { WholeUnitsTable } from "@/components/ledger/WholeUnits";
import { useApi } from "@/lib/use-api";
import { formatDate } from "@/lib/format";
import { useWorkspace } from "@/lib/workspace";
import type { EquityStatement } from "@/lib/types";

/** The statement of changes in equity for one period: opening, what came in, what went out, the period's profit, closing. */
export function EquityPanel({ companyId, periodId, whole }: { companyId: string; periodId: string; whole: boolean }) {
  const { locale } = useWorkspace();
  const { data, error, loading } = useApi<EquityStatement>(`companies/${companyId}/statements/equity`, { periodId, ...(whole ? { whole: "true" } : {}) });
  const title = locale.titles.changes_in_equity;
  return (
    <Card>
      <CardHeader
        title={title}
        description={data ? `${data.period_label}, ${formatDate(data.period_start)} to ${formatDate(data.period_end)}` : undefined}
        actions={
          data ? (
            <>
              <Badge tone={data.agrees_with_balance_sheet ? "pass" : "fail"}>{data.agrees_with_balance_sheet ? "Agrees with the balance sheet" : "Does not agree with the balance sheet"}</Badge>
              <Badge tone={data.profit_agrees ? "pass" : "fail"}>{data.profit_agrees ? "Profit agrees" : "Profit does not agree"}</Badge>
            </>
          ) : null
        }
      />
      {error ? (
        <div className="p-5">
          <Notice kind="error">{error}</Notice>
        </div>
      ) : null}
      {loading && !data ? <Loading /> : null}
      {data ? (
        <>
          <TableWrap>
            <Table>
              <thead>
                <tr>
                  <Th>Component</Th>
                  <Th align="right">Opening</Th>
                  <Th align="right">Increases</Th>
                  <Th align="right">Decreases</Th>
                  <Th align="right">{locale.titles.profit_label}</Th>
                  <Th align="right">Closing</Th>
                </tr>
              </thead>
              <tbody>
                {data.components.map((c) => (
                  <tr key={c.account_id ?? c.kind}>
                    <Td className="font-medium">
                      {c.code ? <span className="num text-ink-soft">{c.code} </span> : null}
                      {c.name}
                    </Td>
                    <Td align="right">
                      <Money value={c.opening} />
                    </Td>
                    <Td align="right">
                      <Money value={c.increases} />
                    </Td>
                    <Td align="right">
                      <Money value={c.decreases} />
                    </Td>
                    <Td align="right">
                      <Money value={c.profit} />
                    </Td>
                    <Td align="right">
                      <Money value={c.closing} />
                    </Td>
                  </tr>
                ))}
                <tr className="bg-paper/60 font-semibold">
                  <Td>Total</Td>
                  <Td align="right">
                    <Money value={data.totals.opening} />
                  </Td>
                  <Td align="right">
                    <Money value={data.totals.increases} />
                  </Td>
                  <Td align="right">
                    <Money value={data.totals.decreases} />
                  </Td>
                  <Td align="right">
                    <Money value={data.totals.profit} />
                  </Td>
                  <Td align="right">
                    <Money value={data.totals.closing} />
                  </Td>
                </tr>
              </tbody>
            </Table>
          </TableWrap>
          {data.presented ? (
            <WholeUnitsTable
              sections={[
                {
                  title: "Closing equity",
                  lines: data.presented.components.map((c) => ({ key: c.account_id ?? c.kind, label: c.name, amount: c.presented ?? "0" })),
                  total: data.presented.closing_total,
                  footing: data.presented.rounding,
                  totalLabel: `Total ${locale.titles.equity_label.toLowerCase()}`,
                },
              ]}
            />
          ) : null}
          <div className="space-y-1.5 border-t border-rule px-5 py-3 text-xs text-ink-faint">
            <p>
              Increases are credits to an equity account in the period and decreases are debits (new capital, drawings, dividends). Milaan makes no year-end closing entries, so profit that has
              not been closed to equity is shown as its own line: opening is the profit of earlier periods, and the {locale.titles.profit_label.toLowerCase()} column is this period&apos;s.
            </p>
            <p>The statement is built from entry dates, the same way as the balance sheet, so the two always use the same entries.</p>
          </div>
        </>
      ) : null}
    </Card>
  );
}