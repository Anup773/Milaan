import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export type Tone = "neutral" | "pass" | "warn" | "fail" | "info" | "ledger";

const TONES: Record<Tone, string> = {
  neutral: "bg-[#ece9df] text-ink-soft",
  pass: "bg-pass-soft text-pass",
  warn: "bg-warn-soft text-warn",
  fail: "bg-fail-soft text-fail",
  info: "bg-info-soft text-info",
  ledger: "bg-ledger-soft text-ledger-dark",
};

export function Badge({ tone = "neutral", children, className }: { tone?: Tone; children: ReactNode; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-medium",
        TONES[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}