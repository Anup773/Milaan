"use client";

import type { ReactNode } from "react";
import { Card, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Table, TableWrap, Td, Th } from "@/components/ui/table";
import { Delta, Money } from "@/components/common/money";
import { formatPct, signOf } from "@/lib/format";
import type { ImpactReport, ImpactRow } from "@/lib/types";

// "Which direction is good news" for the change column, by statement line.
function goodWhenFor(node: string): "up" | "down" | "neutral" {
  if (node === "pl:net_profit" || node === "pl:total_income") return "up";
  if (node === "pl:total_expense") return "down";
  return "neutral";
}

function Rows({ rows, onOpenNode }: { rows: ImpactRow[]; onOpenNode?: (row: ImpactRow) => void }) {
  return (
    <>
      {rows.map((row) => (
        <tr key={row.node}>
          <Td>
            {onOpenNode ? (
              <button type="button" className="text-left font-medium text-ledger-dark underline decoration-ledger/30 underline-offset-2 hover:decoration-ledger" onClick={() => onOpenNode(row)}>
                {row.label}
              </button>
            ) : (
              row.label
            )}
          </Td>
          <Td align="right">
            <Money value={row.current} />
          </Td>
          <Td align="right">
            <Money value={row.scenario} />
          </Td>
          <Td align="right">
            <Delta value={row.delta} goodWhen={goodWhenFor(row.node)} />
          </Td>
          <Td align="right" className="text-ink-soft">
            {formatPct(row.pct_change)}
          </Td>
        </tr>
      ))}
    </>
  );
}

function Section({ title, rows, onOpenNode }: { title: string; rows: ImpactRow[]; onOpenNode?: (row: ImpactRow) => void }) {
  if (rows.length === 0) return null;
  return (
    <Card>
      <CardHeader title={title} />
      <TableWrap>
        <Table>
          <thead>
            <tr>
              <Th>Line</Th>
              <Th align="right">Current</Th>
              <Th align="right">Scenario</Th>
              <Th align="right">Change</Th>
              <Th align="right">%</Th>
            </tr>
          </thead>
          <tbody>
            <Rows rows={rows} onOpenNode={onOpenNode} />
          </tbody>
        </Table>
      </TableWrap>
    </Card>
  );
}

/**
 * The centrepiece table: CURRENT / SCENARIO / CHANGE for every figure a change reaches, from the inputs that were
 * changed, through the profit and loss, to the balance sheet and the balance check. Rendered from the engine's report as-is.
 */
export function ImpactTable({
  report,
  note,
  onOpenAccount,
  header,
}: {
  report: ImpactReport;
  note?: string;
  onOpenAccount?: (row: ImpactRow & { code?: string; name?: string }) => void;
  header?: ReactNode;
}) {
  const { summary } = report;
  const netProfit = report.profit_and_loss.find((r) => r.node === "pl:net_profit");
  const tone = summary.nothing_changes ? "neutral" : signOf(netProfit?.delta) < 0 ? "fail" : "pass";

  return (
    <div className="space-y-4">
      <Card>
        <div className="space-y-3 px-5 py-4">
          {header}
          <p className={`text-base font-semibold ${tone === "fail" ? "text-fail" : tone === "pass" ? "text-pass" : "text-ink"}`}>{summary.headline}</p>
          <div className="flex flex-wrap gap-2 text-xs">
            <Badge tone="info">{summary.figures_changed} figures change</Badge>
            <Badge>{summary.accounts_affected} accounts</Badge>
            <Badge>{summary.statement_lines_affected} statement lines</Badge>
            <Badge tone={summary.balanced_after ? "pass" : "fail"}>{summary.balanced_after ? "Still balances" : "Would not balance"}</Badge>
          </div>
          {note ? <p className="text-xs text-ink-faint">{note}</p> : null}
        </div>
      </Card>

      <Section title="What you changed" rows={report.sources} />
      <Section title="Profit and loss" rows={report.profit_and_loss} />
      <Section title="Balance sheet" rows={report.balance_sheet} />
      {report.accounts.length > 0 ? (
        <Section title="Accounts affected" rows={report.accounts} onOpenNode={onOpenAccount ? (row) => onOpenAccount(row as ImpactRow & { code?: string; name?: string }) : undefined} />
      ) : null}
      <Card>
        <CardHeader title="Balance check" description="Assets minus liabilities, equity and retained earnings. Zero means the books balance." />
        <TableWrap>
          <Table>
            <tbody>
              <tr>
                <Td>Before</Td>
                <Td align="right">
                  <Money value={report.checks.current} />
                </Td>
                <Td>{report.checks.balanced_before ? <Badge tone="pass">Balanced</Badge> : <Badge tone="fail">Not balanced</Badge>}</Td>
              </tr>
              <tr>
                <Td>After the change</Td>
                <Td align="right">
                  <Money value={report.checks.scenario} />
                </Td>
                <Td>{report.checks.balanced_after ? <Badge tone="pass">Balanced</Badge> : <Badge tone="fail">Not balanced</Badge>}</Td>
              </tr>
            </tbody>
          </Table>
        </TableWrap>
      </Card>
    </div>
  );
}
