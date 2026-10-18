"use client";

import Link from "next/link";
import { useState } from "react";
import { Modal } from "@/components/ui/modal";
import { Table, TableWrap, Td, Th } from "@/components/ui/table";
import { Tabs } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { Loading, Notice, Empty } from "@/components/common/notice";
import { Money } from "@/components/common/money";
import { formatDate, humanise, shortId } from "@/lib/format";
import { useApi } from "@/lib/use-api";
import type { Trace, TraceOrigin } from "@/lib/types";

function Origin({ origin }: { origin: TraceOrigin | null }) {
  if (!origin) return <span className="text-ink-faint">-</span>;
  if (origin.type === "source_row") {
    return (
      <span>
        <Badge tone="info">Imported</Badge>{" "}
        <span className="text-ink-soft">
          {origin.filename ?? "file"} - row {origin.row_number ?? "?"}
        </span>
      </span>
    );
  }
  if (origin.type === "adjustment" && origin.adjustment_id) {
    return (
      <span>
        <Badge tone="warn">Adjustment</Badge>{" "}
        <Link href="/adjustments" className="text-ledger underline">
          {shortId(origin.adjustment_id)}
        </Link>
      </span>
    );
  }
  return <Badge>{humanise(origin.type)}</Badge>;
}

/**
 * "Where did this number come from?": an account's ledger lines for the period, each with the file and row
 * (or the approved adjustment) it came from. This is the lower half of the drill-down chain from the plan.
 */
export function DrillDown({
  companyId,
  periodId,
  accountId,
  accountLabel,
  onClose,
}: {
  companyId: string;
  periodId: string;
  accountId: string | null;
  accountLabel: string;
  onClose: () => void;
}) {
  const [scope, setScope] = useState<"period" | "cumulative">("period");
  const { data, error, loading } = useApi<Trace>(
    accountId ? `companies/${companyId}/dependency-graph/trace` : null,
    { periodId, accountId, scope },
  );

  return (
    <Modal open={accountId !== null} onClose={onClose} title={`Where this comes from - ${accountLabel}`} wide>
      <div className="space-y-4">
        <Tabs
          tabs={[
            { id: "period" as const, label: "This period" },
            { id: "cumulative" as const, label: "Everything up to period end" },
          ]}
          value={scope}
          onChange={setScope}
        />
        {loading && !data ? <Loading /> : null}
        {error ? <Notice kind="error">{error}</Notice> : null}
        {data && data.lines.length === 0 ? <Empty title="No ledger lines" /> : null}
        {data && data.lines.length > 0 ? (
          <TableWrap>
            <Table>
              <thead>
                <tr>
                  <Th>Date</Th>
                  <Th>Entry</Th>
                  <Th align="right">Debit</Th>
                  <Th align="right">Credit</Th>
                  <Th>Came from</Th>
                </tr>
              </thead>
              <tbody>
                {data.lines.map((line, i) => (
                  <tr key={`${line.journal_entry_id}-${i}`}>
                    <Td className="whitespace-nowrap">{formatDate(line.entry_date)}</Td>
                    <Td>{line.description || <span className="text-ink-faint">-</span>}</Td>
                    <Td align="right">
                      <Money value={line.debit} />
                    </Td>
                    <Td align="right">
                      <Money value={line.credit} />
                    </Td>
                    <Td>
                      <Origin origin={line.origin} />
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </TableWrap>
        ) : null}
      </div>
    </Modal>
  );
}