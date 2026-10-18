"use client";

import { useState, type FormEvent } from "react";
import { PageHeader } from "@/components/common/page-header";
import { Gate } from "@/components/common/gate";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Field, Input, Select } from "@/components/ui/form";
import { Modal } from "@/components/ui/modal";
import { Table, TableWrap, Td, Th } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Empty, Loading, Notice } from "@/components/common/notice";
import { Money } from "@/components/common/money";
import { api, errorMessage } from "@/lib/api-client";
import { useApi } from "@/lib/use-api";
import { CAN, can, type Role } from "@/lib/roles";
import { formatDate, humanise, isDecimal } from "@/lib/format";
import type { Account, FixedAsset, Period, Rollforward, ScheduleReconcile } from "@/lib/types";

function AddAsset({ companyId, accounts, onDone }: { companyId: string; accounts: Account[]; onDone: () => void }) {
  const assets = accounts.filter((a) => a.account_type === "Asset");
  const expenses = accounts.filter((a) => a.account_type === "Expense");
  const [name, setName] = useState("");
  const [date, setDate] = useState("");
  const [cost, setCost] = useState("");
  const [salvage, setSalvage] = useState("0");
  const [life, setLife] = useState("");
  const [assetAcc, setAssetAcc] = useState("");
  const [accumAcc, setAccumAcc] = useState("");
  const [expenseAcc, setExpenseAcc] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    const costNumber = Number(cost);
    const salvageNumber = Number(salvage || "0");
    const months = Number(life);
    if (!isDecimal(cost) || costNumber <= 0) return setError("Cost must be an amount above zero.");
    if (!isDecimal(salvage || "0") || salvageNumber < 0) return setError("Salvage value cannot be negative.");
    if (salvageNumber >= costNumber) return setError("Salvage value must be less than the cost.");
    if (!Number.isInteger(months) || months <= 0) return setError("Useful life must be a whole number of months.");
    setBusy(true);
    try {
      await api(`companies/${companyId}/fixed-assets`, {
        method: "POST",
        body: {
          name: name.trim(),
          acquisitionDate: date,
          cost: costNumber,
          salvageValue: salvageNumber,
          usefulLifeMonths: months,
          assetAccountId: assetAcc,
          accumulatedDepreciationAccountId: accumAcc,
          depreciationExpenseAccountId: expenseAcc,
        },
      });
      setName("");
      setDate("");
      setCost("");
      setSalvage("0");
      setLife("");
      onDone();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const ready = name.trim() && date && cost && life && assetAcc && accumAcc && expenseAcc;
  return (
    <Card>
      <CardHeader title="Add a fixed asset" description="Straight-line depreciation. The three accounts must be the right kinds, or the books would stop balancing." />
      <CardBody>
        {assets.length < 2 || expenses.length < 1 ? (
          <Notice kind="info" className="mb-4">
            You need at least two Asset accounts (the asset and its accumulated depreciation) and one Expense account (depreciation expense). Add them through the mappings page.
          </Notice>
        ) : null}
        <form onSubmit={submit} className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <Field label="Name" htmlFor="fa-name" className="lg:col-span-2">
            <Input id="fa-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="CNC machine" />
          </Field>
          <Field label="Acquired on" htmlFor="fa-date">
            <Input id="fa-date" type="date" value={date} onChange={(e) => setDate(e.target.value)} />
          </Field>
          <Field label="Cost" htmlFor="fa-cost">
            <Input id="fa-cost" inputMode="decimal" value={cost} onChange={(e) => setCost(e.target.value)} placeholder="540000" />
          </Field>
          <Field label="Salvage value" htmlFor="fa-salvage">
            <Input id="fa-salvage" inputMode="decimal" value={salvage} onChange={(e) => setSalvage(e.target.value)} />
          </Field>
          <Field label="Useful life (months)" htmlFor="fa-life">
            <Input id="fa-life" inputMode="numeric" value={life} onChange={(e) => setLife(e.target.value)} placeholder="120" />
          </Field>
          <Field label="Asset account" htmlFor="fa-asset">
            <Select id="fa-asset" value={assetAcc} onChange={(e) => setAssetAcc(e.target.value)}>
              <option value="">Choose...</option>
              {assets.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.code} {a.name}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Accumulated depreciation account" htmlFor="fa-accum">
            <Select id="fa-accum" value={accumAcc} onChange={(e) => setAccumAcc(e.target.value)}>
              <option value="">Choose...</option>
              {assets.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.code} {a.name}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Depreciation expense account" htmlFor="fa-expense">
            <Select id="fa-expense" value={expenseAcc} onChange={(e) => setExpenseAcc(e.target.value)}>
              <option value="">Choose...</option>
              {expenses.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.code} {a.name}
                </option>
              ))}
            </Select>
          </Field>
          <div className="flex items-end sm:col-span-2 lg:col-span-3">
            <Button type="submit" loading={busy} disabled={!ready}>
              Add asset
            </Button>
          </div>
        </form>
        {error ? <Notice kind="error" className="mt-3">{error}</Notice> : null}
      </CardBody>
    </Card>
  );
}

function Schedules({ companyId, period, role }: { companyId: string; period: Period | null; role: Role }) {
  const accounts = useApi<{ accounts: Account[] }>(`companies/${companyId}/accounts`);
  const assets = useApi<{ fixedAssets: FixedAsset[] }>(`companies/${companyId}/fixed-assets`);
  const roll = useApi<Rollforward>(period ? `companies/${companyId}/schedules/fixed-assets` : null, { periodId: period?.id });
  const recon = useApi<ScheduleReconcile>(period ? `companies/${companyId}/schedules/fixed-assets/reconcile` : null, { periodId: period?.id });
  const [confirming, setConfirming] = useState(false);
  const [posting, setPosting] = useState(false);
  const [message, setMessage] = useState<{ kind: "success" | "error"; text: string } | null>(null);

  async function postDepreciation() {
    if (!period) return;
    setPosting(true);
    setMessage(null);
    try {
      const result = await api<Record<string, unknown>>(`companies/${companyId}/schedules/fixed-assets/post-depreciation`, {
        method: "POST",
        body: { periodId: period.id },
      });
      setMessage({ kind: "success", text: `Depreciation posted. ${summariseResult(result)}` });
      setConfirming(false);
      roll.reload();
      recon.reload();
    } catch (err) {
      setMessage({ kind: "error", text: errorMessage(err) });
      setConfirming(false);
    } finally {
      setPosting(false);
    }
  }

  const accountName = (id: string) => {
    const a = accounts.data?.accounts.find((x) => x.id === id);
    return a ? `${a.code} ${a.name}` : id.slice(0, 8);
  };

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader title="Fixed assets" />
        {assets.error ? (
          <CardBody>
            <Notice kind="error">{assets.error}</Notice>
          </CardBody>
        ) : null}
        {assets.loading && !assets.data ? <Loading /> : null}
        {assets.data && assets.data.fixedAssets.length === 0 ? <Empty title="No fixed assets yet">Add the first one below.</Empty> : null}
        {assets.data && assets.data.fixedAssets.length > 0 ? (
          <TableWrap>
            <Table>
              <thead>
                <tr>
                  <Th>Asset</Th>
                  <Th>Acquired</Th>
                  <Th align="right">Cost</Th>
                  <Th align="right">Salvage</Th>
                  <Th align="right">Life (months)</Th>
                  <Th>Method</Th>
                  <Th>Accounts</Th>
                </tr>
              </thead>
              <tbody>
                {assets.data.fixedAssets.map((a) => (
                  <tr key={a.id}>
                    <Td className="font-medium">
                      {a.name} {a.disposed_date ? <Badge>Disposed {formatDate(a.disposed_date)}</Badge> : null}
                    </Td>
                    <Td className="whitespace-nowrap">{formatDate(a.acquisition_date)}</Td>
                    <Td align="right">
                      <Money value={a.cost} />
                    </Td>
                    <Td align="right">
                      <Money value={a.salvage_value} />
                    </Td>
                    <Td align="right">{a.useful_life_months}</Td>
                    <Td>{humanise(a.depreciation_method)}</Td>
                    <Td className="text-xs text-ink-soft">
                      <div>{accountName(a.asset_account_id)}</div>
                      <div>{accountName(a.accumulated_depreciation_account_id)}</div>
                      <div>{accountName(a.depreciation_expense_account_id)}</div>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </TableWrap>
        ) : null}
      </Card>

      {period ? (
        <>
          <Card>
            <CardHeader
              title={`Depreciation roll-forward - ${period.label}`}
              description="Opening value, this period's depreciation and closing value for each asset"
              actions={
                can(role, CAN.postDepreciation) && period.lock_status === "OPEN" ? (
                  <Button size="sm" onClick={() => setConfirming(true)} disabled={!roll.data || roll.data.assets.length === 0}>
                    Post depreciation
                  </Button>
                ) : null
              }
            />
            {roll.error ? (
              <CardBody>
                <Notice kind="error">{roll.error}</Notice>
              </CardBody>
            ) : null}
            {roll.loading && !roll.data ? <Loading /> : null}
            {roll.data && roll.data.assets.length === 0 ? <Empty title="Nothing to depreciate in this period" /> : null}
            {roll.data && roll.data.assets.length > 0 ? (
              <TableWrap>
                <Table>
                  <thead>
                    <tr>
                      <Th>Asset</Th>
                      <Th align="right">Cost</Th>
                      <Th align="right">Accumulated before</Th>
                      <Th align="right">Opening value</Th>
                      <Th align="right">Depreciation</Th>
                      <Th align="right">Closing value</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {roll.data.assets.map((r) => (
                      <tr key={r.fixed_asset_id}>
                        <Td className="font-medium">{r.name}</Td>
                        <Td align="right">
                          <Money value={r.cost} />
                        </Td>
                        <Td align="right">
                          <Money value={r.accumulated_before_period} />
                        </Td>
                        <Td align="right">
                          <Money value={r.opening_wdv} />
                        </Td>
                        <Td align="right">
                          <Money value={r.depreciation_this_period} />
                        </Td>
                        <Td align="right">
                          <Money value={r.closing_wdv} />
                        </Td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              </TableWrap>
            ) : null}
            {message ? (
              <CardBody className="border-t border-rule">
                <Notice kind={message.kind}>{message.text}</Notice>
              </CardBody>
            ) : null}
          </Card>

          <Card>
            <CardHeader title="Does the schedule agree with the ledger?" description="The depreciation the schedule has posted against what the ledger's accumulated-depreciation account holds" />
            {recon.error ? (
              <CardBody>
                <Notice kind="error">{recon.error}</Notice>
              </CardBody>
            ) : null}
            {recon.loading && !recon.data ? <Loading /> : null}
            {recon.data && recon.data.assets.length === 0 ? <Empty title="No assets to compare" /> : null}
            {recon.data && recon.data.assets.length > 0 ? (
              <TableWrap>
                <Table>
                  <thead>
                    <tr>
                      <Th>Asset</Th>
                      <Th align="right">Schedule posted</Th>
                      <Th align="right">Account schedule total</Th>
                      <Th align="right">Ledger balance</Th>
                      <Th>Result</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {recon.data.assets.map((r) => (
                      <tr key={r.fixed_asset_id}>
                        <Td className="font-medium">{r.name}</Td>
                        <Td align="right">
                          <Money value={r.schedule_accumulated_depreciation} />
                        </Td>
                        <Td align="right">
                          <Money value={r.account_schedule_total} />
                        </Td>
                        <Td align="right">
                          <Money value={r.ledger_accumulated_depreciation_account_balance} />
                        </Td>
                        <Td>{r.matches ? <Badge tone="pass">Agrees</Badge> : <Badge tone="fail">Differs</Badge>}</Td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              </TableWrap>
            ) : null}
          </Card>
        </>
      ) : (
        <Notice kind="info">Choose or create an accounting period to see the depreciation schedule.</Notice>
      )}

      {can(role, CAN.createFixedAsset) ? (
        <AddAsset
          companyId={companyId}
          accounts={accounts.data?.accounts ?? []}
          onDone={() => {
            assets.reload();
            roll.reload();
            recon.reload();
          }}
        />
      ) : (
        <Notice kind="info">Adding a fixed asset needs a senior accountant, CA or admin.</Notice>
      )}

      <Modal
        open={confirming}
        onClose={() => setConfirming(false)}
        title="Post depreciation to the ledger?"
        footer={
          <>
            <Button variant="secondary" onClick={() => setConfirming(false)}>
              Cancel
            </Button>
            <Button loading={posting} onClick={() => void postDepreciation()}>
              Post depreciation
            </Button>
          </>
        }
      >
        <p className="text-sm text-ink-soft">
          This writes journal entries for {period?.label}: it debits depreciation expense and credits accumulated depreciation for each asset. It is recorded in the audit trail and cannot be edited afterwards. A period that is already locked cannot take it.
        </p>
      </Modal>
    </div>
  );
}

/** A short sentence out of whatever the engine returned, without assuming its exact fields. */
function summariseResult(result: Record<string, unknown>): string {
  const parts: string[] = [];
  for (const [key, value] of Object.entries(result)) {
    if (typeof value === "number") parts.push(`${humanise(key)}: ${value}`);
  }
  return parts.join(", ");
}

export default function SchedulesPage() {
  return (
    <>
      <PageHeader title="Schedules" description="Fixed assets and their depreciation: what the schedule says, whether the ledger agrees, and posting the period's depreciation." />
      <Gate>{({ company, period, role }) => <Schedules key={`${company.id}:${period?.id ?? "none"}`} companyId={company.id} period={period} role={role} />}</Gate>
    </>
  );
}