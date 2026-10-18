import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export function Stat({ label, value, sub, tone, className }: { label: string; value: ReactNode; sub?: ReactNode; tone?: "pass" | "warn" | "fail"; className?: string }) {
  return (
    <div className={cn("rounded-lg border border-rule bg-card px-4 py-3.5", className)}>
      <div className="text-xs font-medium uppercase tracking-wide text-ink-faint">{label}</div>
      <div
        className={cn(
          "num mt-1 text-xl font-semibold",
          tone === "pass" && "text-pass",
          tone === "warn" && "text-warn",
          tone === "fail" && "text-fail",
          !tone && "text-ink",
        )}
      >
        {value}
      </div>
      {sub ? <div className="mt-0.5 text-xs text-ink-soft">{sub}</div> : null}
    </div>
  );
}