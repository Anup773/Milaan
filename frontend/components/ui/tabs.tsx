"use client";

import { cn } from "@/lib/utils";

export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
}: {
  tabs: Array<{ id: T; label: string; count?: number }>;
  value: T;
  onChange: (id: T) => void;
}) {
  return (
    <div role="tablist" className="flex flex-wrap gap-1 border-b border-rule">
      {tabs.map((tab) => {
        const active = tab.id === value;
        return (
          <button
            key={tab.id}
            role="tab"
            type="button"
            aria-selected={active}
            onClick={() => onChange(tab.id)}
            className={cn(
              "-mb-px border-b-2 px-3.5 py-2 text-sm font-medium transition-colors",
              active ? "border-ledger text-ledger-dark" : "border-transparent text-ink-soft hover:text-ink",
            )}
          >
            {tab.label}
            {tab.count !== undefined ? (
              <span className="ml-1.5 rounded-full bg-[#ece9df] px-1.5 py-0.5 text-[11px] text-ink-soft">{tab.count}</span>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}