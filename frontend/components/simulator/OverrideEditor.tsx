"use client";

import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/form";
import { Money } from "@/components/common/money";
import { parseAmountInput } from "@/lib/format";
import type { GraphNode } from "@/lib/types";

export interface OverrideRow {
  key: number;
  nodeId: string;
  amount: string;
}

/** The overrides object the API wants ({ nodeId: "amount" }), or an error saying what is wrong. */
export function overridesFrom(rows: OverrideRow[]): { overrides: Record<string, string> } | { error: string } {
  const out: Record<string, string> = {};
  for (const row of rows) {
    if (!row.nodeId) return { error: "Choose which figure to change on every row." };
    const amount = parseAmountInput(row.amount);
    if (amount === null) return { error: "Each new value must be a number with at most two decimals." };
    if (row.nodeId in out) return { error: "The same figure is listed twice." };
    out[row.nodeId] = amount;
  }
  if (Object.keys(out).length === 0) return { error: "Add at least one change." };
  return { overrides: out };
}

/**
 * Rows of "change this figure to that value". Only the figures that are inputs (the ledger leaves of the dependency graph) can be
 * changed; everything downstream is recomputed by the engine.
 */
export function OverrideEditor({
  nodes,
  rows,
  onChange,
  nextKey,
  disabled,
}: {
  nodes: GraphNode[];
  rows: OverrideRow[];
  onChange: (rows: OverrideRow[]) => void;
  nextKey: () => number;
  disabled?: boolean;
}) {
  const inputs = nodes.filter((n) => n.is_leaf).sort((a, b) => a.label.localeCompare(b.label));
  const byId = new Map(nodes.map((n) => [n.id, n]));

  function update(key: number, patch: Partial<OverrideRow>) {
    onChange(rows.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  }

  return (
    <div className="space-y-2">
      {rows.map((row, index) => {
        const node = row.nodeId ? byId.get(row.nodeId) : undefined;
        return (
          <div key={row.key} className="grid items-center gap-2 sm:grid-cols-[1fr_9rem_9rem_auto]">
            <Select aria-label={`Figure to change, row ${index + 1}`} value={row.nodeId} onChange={(e) => update(row.key, { nodeId: e.target.value })} disabled={disabled}>
              <option value="">Choose a figure...</option>
              {inputs.map((n) => (
                <option key={n.id} value={n.id}>
                  {n.label}
                </option>
              ))}
            </Select>
            <div className="text-right text-sm text-ink-soft" aria-label="Current value">
              {node ? (
                <>
                  <span className="mr-1 text-xs text-ink-faint">now</span>
                  <Money value={node.value} />
                </>
              ) : null}
            </div>
            <Input
              aria-label={`New value, row ${index + 1}`}
              inputMode="decimal"
              placeholder="New value"
              value={row.amount}
              onChange={(e) => update(row.key, { amount: e.target.value })}
              className="num text-right"
              disabled={disabled}
            />
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={disabled || rows.length <= 1}
              aria-label={`Remove row ${index + 1}`}
              onClick={() => onChange(rows.filter((r) => r.key !== row.key))}
            >
              Remove
            </Button>
          </div>
        );
      })}
      <Button type="button" variant="secondary" size="sm" disabled={disabled} onClick={() => onChange([...rows, { key: nextKey(), nodeId: "", amount: "" }])}>
        + Change another figure
      </Button>
    </div>
  );
}
