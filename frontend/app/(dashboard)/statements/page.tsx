"use client";

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import { PageHeader } from "@/components/common/page-header";
import { Gate } from "@/components/common/gate";
import { Card, CardHeader } from "@/components/ui/card";
import { Tabs } from "@/components/ui/tabs";
import { Select, Field } from "@/components/ui/form";
import { Table, TableWrap, Td, Th } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Loading, Notice, Empty } from "@/components/common/notice";
import { Money } from "@/components/common/money";
import { DrillDown } from "@/components/ledger/DrillDown";
import { useApi } from "@/lib/use-api";
import { formatDate, sameAmount, signOf } from "@/lib/format";
import type {
  Account,
  BalanceSheet,
  BalanceSheetLine,
  CashFlow,
  GeneralLedger,
  ProfitLoss,
  TrialBalance,
  TrialBalanceLine,
} from "@/lib/types";

type Tab = "tb" | "pl" | "bs" | "cf" | "gl";

const TABS: Array<{ id: Tab; label: string }> = [
  { id: "tb", label: "Trial balance" },
  { id: "pl", label: "Profit & loss" },
  { id: "bs", label: "Balance sheet" },
  { id: "cf", label: "Cash flow" },
  { id: "gl", label: "General ledger" },
];

interface Ctx {
  companyId: string;
  periodId: string;
  periodEnd: string;
  openAccount: (id: string, label: string) => void;
}

function AccountLink({ id, code, name, onOpen }: { id: string; code: string; name: string; onOpen: Ctx["openAccount"] }) {
  return (
    <button
      type="button"
      onClick={() => onOpen(id, `${code} ${name}`)}
      className="text-left font-medium text-ledger-dark underline decoration-ledger/30 underline-offset-2 hover:decoration-ledger"
      title="Show where this comes from"
    >
      <span className="num text-ink-soft">{code}</span> {name}
    </button>
  );
}

function PanelState({ loading, error, hasData }: { loading: boolean; error: string | null; hasData: boolean }) {
  if (error) {
    return (
      <div className="p-5">
        <Notice kind="error">{error}</Notice>
      </div>
    );
  }
  if (loading && !hasData) return <Loading />;
  return null;
}

function TrialBalancePanel({ companyId, periodId, openAccount }: Ctx) {
  const { data, error, loading } = useApi<TrialBalance>(`companies/${companyId}/statements/trial-balance`, { periodId });
  const balanced = data ? sameAmount(data.total_debit, data.total_credit) : false;
  return (
    <Card>
      <CardHeader
        title="Trial balance"
        description={data ? `${data.period_label}, ${formatDate(data.period_start)} to ${formatDate(data.period_end)}` : undefined}
        actions={data ? <Badge tone={balanced ? "pass" : "fail"}>{balanced ? "Debits equal credits" : "Out of balance"}</Badge> : null}
      />
      <PanelState loading={loading} error={error} hasData={!!data} />
      {data && data.lines.length === 0 ? <Empty title="Nothing posted in this period" /> : null}
      {data && data.lines.length > 0 ? (
        <TableWrap>
          <Table>
            <thead>
              <tr>
                <Th>Account</Th>
                <Th>Type</Th>
                <Th align="right">Debit</Th>
                <Th align="right">Credit</Th>
                <Th align="right">Balance</Th>
              </tr>
            </thead>
            <tbody>
              {data.lines.map((l) => (
                <tr key={l.account_id}>
                  <Td>
                    <AccountLink id={l.account_id} code={l.code} name={l.name} onOpen={openAccount} />
                  </Td>
                  <Td className="text-ink-soft">{l.account_type}</Td>
                  <Td align="right">
                    <Money value={l.total_debit} />
                  </Td>
                  <Td align="right">
                    <Money value={l.total_credit} />
                  </Td>
                  <Td align="right">
                    <Money value={l.balance} />
                  </Td>
                </tr>
              ))}
              <tr className="bg-paper/60 font-semibold">
                <Td>Total</Td>
                <Td />
                <Td align="right">
                  <Money value={data.total_debit} />
                </Td>
                <Td align="right">
                  <Money value={data.total_credit} />
                </Td>
                <Td />
              </tr>
            </tbody>
          </Table>
        </TableWrap>
      ) : null}
    </Card>
  );
}

function LinesTable({ lines, onOpen }: { lines: TrialBalanceLine[]; onOpen: Ctx["openAccount"] }) {
  if (lines.length === 0) return <div className="px-4 py-3 text-sm text-ink-faint">None</div>;
  return (
    <Table>
      <tbody>
        {lines.map((l) => (
          <tr key={l.account_id}>
            <Td>
              <AccountLink id={l.account_id} code={l.code} name={l.name} onOpen={onOpen} />
            </Td>
            <Td align="right">
              <Money value={l.balance} />
            </Td>
          </tr>
        ))}
      </tbody>
    </Table>
  );
}

function ProfitLossPanel({ companyId, periodId, openAccount }: Ctx) {
  const { data, error, loading } = useApi<ProfitLoss>(`companies/${companyId}/statements/profit-loss`, { periodId });
  return (
    <Card>
      <CardHeader
        title="Profit & loss"
        description={data ? `${data.period_label}, ${formatDate(data.period_start)} to ${formatDate(data.period_end)}` : undefined}
      />
      <PanelState loading={loading} error={error} hasData={!!data} />
      {data ? (
        <TableWrap>
          <div className="bg-paper/60 px-4 py-2 text-xs font-semibold uppercase tracking-wide text-ink-soft">Income</div>
          <LinesTable lines={data.income} onOpen={openAccount} />
          <div className="flex justify-between border-b border-rule px-4 py-2.5 text-sm font-semibold">
            <span>Total income</span>
            <Money value={data.total_income} />
          </div>
          <div className="bg-paper/60 px-4 py-2 text-xs font-semibold uppercase tracking-wide text-ink-soft">Expenses</div>
          <LinesTable lines={data.expense} onOpen={openAccount} />
          <div className="flex justify-between border-b border-rule px-4 py-2.5 text-sm font-semibold">
            <span>Total expenses</span>
            <Money value={data.total_expense} />
          </div>
          <div className="flex justify-between px-4 py-3 text-base font-semibold">
            <span>{signOf(data.net_profit) < 0 ? "Net loss" : "Net profit"}</span>
            <Money value={data.net_profit} className={signOf(data.net_profit) < 0 ? "text-fail" : "text-pass"} />
          </div>
        </TableWrap>
      ) : null}
    </Card>
  );
}

function BsSection({ title, lines, total, onOpen }: { title: string; lines: BalanceSheetLine[]; total?: string; onOpen: Ctx["openAccount"] }) {
  return (
    <>
      <div className="bg-paper/60 px-4 py-2 text-xs font-semibold uppercase tracking-wide text-ink-soft">{title}</div>
      {lines.length === 0 ? (
        <div className="px-4 py-3 text-sm text-ink-faint">None</div>
      ) : (
        <Table>
          <tbody>
            {lines.map((l) => (
              <tr key={l.account_id}>
                <Td>
                  <AccountLink id={l.account_id} code={l.code} name={l.name} onOpen={onOpen} />
                </Td>
                <Td align="right">
                  <Money value={l.balance} />
                </Td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
      {total !== undefined ? (
        <div className="flex justify-between border-b border-rule px-4 py-2.5 text-sm font-semibold">
          <span>Total {title.toLowerCase()}</span>
          <Money value={total} />
        </div>
      ) : null}
    </>
  );
}

function BalanceSheetPanel({ companyId, periodEnd, openAccount }: Ctx) {
  const { data, error, loading } = useApi<BalanceSheet>(`companies/${companyId}/statements/balance-sheet`, { asOfDate: periodEnd });
  return (
    <Card>
      <CardHeader
        title="Balance sheet"
        description={data ? `As of ${formatDate(data.as_of_date)}` : undefined}
        actions={data ? <Badge tone={data.balances ? "pass" : "fail"}>{data.balances ? "Balances" : "Does not balance"}</Badge> : null}
      />
      <PanelState loading={loading} error={error} hasData={!!data} />
      {data ? (
        <TableWrap>
          <BsSection title="Assets" lines={data.assets} total={data.total_assets} onOpen={openAccount} />
          <BsSection title="Liabilities" lines={data.liabilities} total={data.total_liabilities} onOpen={openAccount} />
          <BsSection title="Equity" lines={data.equity} onOpen={openAccount} />
          <div className="flex justify-between border-b border-rule px-4 py-2.5 text-sm">
            <span>Retained earnings</span>
            <Money value={data.retained_earnings} />
          </div>
          <div className="flex justify-between px-4 py-3 text-sm font-semibold">
            <span>Total equity and retained earnings</span>
            <Money value={data.total_equity_and_retained_earnings} />
          </div>
        </TableWrap>
      ) : null}
    </Card>
  );
}

function CashFlowPanel({ companyId, periodId }: Ctx) {
  const { data, error, loading } = useApi<CashFlow>(`companies/${companyId}/statements/cash-flow`, { periodId });
  return (
    <Card>
      <CardHeader
        title="Cash flow"
        description={data ? `${data.period_label}, ${formatDate(data.period_start)} to ${formatDate(data.period_end)}` : undefined}
      />
      <PanelState loading={loading} error={error} hasData={!!data} />
      {data ? (
        <div className="space-y-4 p-5">
          <div className="flex items-baseline justify-between">
            <span className="text-sm text-ink-soft">Net cash flow</span>
            <Money value={data.net_cash_flow} className="text-xl font-semibold" />
          </div>
          {data.cash_accounts.length === 0 ? (
            <Notice kind="info">No account is marked as a cash account yet, so there is no cash movement to show.</Notice>
          ) : (
            <pre className="overflow-x-auto rounded-md bg-paper p-3 text-xs">{JSON.stringify(data.cash_accounts, null, 2)}</pre>
          )}
          {data.note ? <p className="text-xs text-ink-faint">{data.note}</p> : null}
        </div>
      ) : null}
    </Card>
  );
}

function GeneralLedgerPanel({ companyId, periodId }: Ctx) {
  const accounts = useApi<{ accounts: Account[] }>(`companies/${companyId}/accounts`);
  const [accountId, setAccountId] = useState("");
  const chosen = accountId || accounts.data?.accounts[0]?.id || "";
  const { data, error, loading } = useApi<GeneralLedger>(chosen ? `companies/${companyId}/statements/general-ledger` : null, {
    accountId: chosen,
    periodId,
  });
  return (
    <Card>
      <CardHeader title="General ledger" description="Every posting to one account, with a running balance" />
      <div className="border-b border-rule px-5 py-3">
        <Field label="Account" htmlFor="gl-account" className="max-w-sm">
          <Select
            id="gl-account"
            value={chosen}
            onChange={(e) => setAccountId(e.target.value)}
            disabled={!accounts.data || accounts.data.accounts.length === 0}
          >
            {(accounts.data?.accounts ?? []).map((a) => (
              <option key={a.id} value={a.id}>
                {a.code} {a.name}
              </option>
            ))}
          </Select>
        </Field>
      </div>
      {accounts.error ? (
        <div className="p-5">
          <Notice kind="error">{accounts.error}</Notice>
        </div>
      ) : null}
      {accounts.data && accounts.data.accounts.length === 0 ? <Empty title="No accounts yet">Import a file and map its accounts first.</Empty> : null}
      <PanelState loading={loading} error={error} hasData={!!data} />
      {data ? (
        <TableWrap>
          <Table>
            <thead>
              <tr>
                <Th>Date</Th>
                <Th>Entry</Th>
                <Th align="right">Debit</Th>
                <Th align="right">Credit</Th>
                <Th align="right">Balance</Th>
              </tr>
            </thead>
            <tbody>
              <tr className="bg-paper/60">
                <Td colSpan={4} className="text-ink-soft">
                  Opening balance
                </Td>
                <Td align="right">
                  <Money value={data.opening_balance} />
                </Td>
              </tr>
              {data.lines.map((l, i) => (
                <tr key={`${l.journal_entry_id}-${i}`}>
                  <Td className="whitespace-nowrap">{formatDate(l.entry_date)}</Td>
                  <Td>{l.description}</Td>
                  <Td align="right">
                    <Money value={l.debit} />
                  </Td>
                  <Td align="right">
                    <Money value={l.credit} />
                  </Td>
                  <Td align="right">
                    <Money value={l.running_balance} />
                  </Td>
                </tr>
              ))}
              <tr className="bg-paper/60 font-semibold">
                <Td colSpan={4}>Closing balance</Td>
                <Td align="right">
                  <Money value={data.closing_balance} />
                </Td>
              </tr>
            </tbody>
          </Table>
        </TableWrap>
      ) : null}
    </Card>
  );
}

function Statements({ companyId, periodId, periodEnd }: { companyId: string; periodId: string; periodEnd: string }) {
  const params = useSearchParams();
  const initial = params.get("tab");
  const [tab, setTab] = useState<Tab>(TABS.some((t) => t.id === initial) ? (initial as Tab) : "tb");
  const [drill, setDrill] = useState<{ id: string; label: string } | null>(null);
  const ctx: Ctx = { companyId, periodId, periodEnd, openAccount: (id, label) => setDrill({ id, label }) };

  return (
    <div className="space-y-4">
      <Tabs tabs={TABS} value={tab} onChange={setTab} />
      {tab === "tb" ? <TrialBalancePanel {...ctx} /> : null}
      {tab === "pl" ? <ProfitLossPanel {...ctx} /> : null}
      {tab === "bs" ? <BalanceSheetPanel {...ctx} /> : null}
      {tab === "cf" ? <CashFlowPanel {...ctx} /> : null}
      {tab === "gl" ? <GeneralLedgerPanel {...ctx} /> : null}
      <DrillDown
        companyId={companyId}
        periodId={periodId}
        accountId={drill?.id ?? null}
        accountLabel={drill?.label ?? ""}
        onClose={() => setDrill(null)}
      />
    </div>
  );
}

export default function StatementsPage() {
  return (
    <>
      <PageHeader
        title="Statements"
        description="The books as posted: trial balance, profit and loss, balance sheet, cash flow and the general ledger. Click an account to see where each figure came from."
      />
      <Gate needsPeriod>
        {({ company, period }) =>
          period ? (
            <Suspense fallback={<Loading />}>
              <Statements key={`${company.id}:${period.id}`} companyId={company.id} periodId={period.id} periodEnd={period.period_end} />
            </Suspense>
          ) : null
        }
      </Gate>
    </>
  );
}