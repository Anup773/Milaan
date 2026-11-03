"use client";

import { Table, TableWrap, Td } from "@/components/ui/table";
import { Whole } from "@/components/common/money";
import { isDecimal } from "@/lib/format";

export interface WholeSection {
  title: string;
  lines: Array<{ key: string; label: string; amount: string }>;
  /** The exact total, rounded. */
  total: string;
  /** The rounded total minus the sum of the rounded lines. Shown as its own line when it is not zero, never hidden. */
  footing: string;
  totalLabel?: string;
}

function nonZero(value: string): boolean {
  return isDecimal(value) && Number(value) !== 0;
}

/**
 * A statement in whole units (rupees or dollars), the way a signed statement is printed. Each line is rounded on its own and the
 * total is the rounded exact total, so the lines can differ from the total by a unit or two: that difference is shown as a
 * "Rounding" line, so nothing is hidden.
 */
export function WholeUnitsTable({ sections, note }: { sections: WholeSection[]; note?: string }) {
  return (
    <div>
      <div className="border-t border-rule bg-paper/40 px-4 py-2 text-xs text-ink-soft">
        In whole units. Each line is rounded on its own; the ledger itself keeps exact amounts.
      </div>
      <TableWrap>
        <Table>
          <tbody>
            {sections.map((s) => (
              <SectionRows key={s.title} section={s} />
            ))}
          </tbody>
        </Table>
      </TableWrap>
      {note ? <p className="px-4 py-2 text-xs text-ink-faint">{note}</p> : null}
    </div>
  );
}

function SectionRows({ section }: { section: WholeSection }) {
  return (
    <>
      <tr>
        <Td colSpan={2} className="bg-paper/60 text-xs font-semibold uppercase tracking-wide text-ink-soft">
          {section.title}
        </Td>
      </tr>
      {section.lines.map((l) => (
        <tr key={l.key}>
          <Td>{l.label}</Td>
          <Td align="right">
            <Whole value={l.amount} />
          </Td>
        </tr>
      ))}
      {nonZero(section.footing) ? (
        <tr>
          <Td className="text-ink-soft">Rounding (the exact total, rounded, minus the rounded lines)</Td>
          <Td align="right">
            <Whole value={section.footing} />
          </Td>
        </tr>
      ) : null}
      <tr className="font-semibold">
        <Td>{section.totalLabel ?? `Total ${section.title.toLowerCase()}`}</Td>
        <Td align="right">
          <Whole value={section.total} />
        </Td>
      </tr>
    </>
  );
}