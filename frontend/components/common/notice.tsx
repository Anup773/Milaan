import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

type Kind = "error" | "success" | "info" | "warning";

const KINDS: Record<Kind, string> = {
  error: "border-fail/30 bg-fail-soft text-fail",
  success: "border-pass/30 bg-pass-soft text-pass",
  info: "border-info/30 bg-info-soft text-info",
  warning: "border-warn/30 bg-warn-soft text-warn",
};

export function Notice({ kind = "info", children, className }: { kind?: Kind; children: ReactNode; className?: string }) {
  return (
    <div
      role={kind === "error" ? "alert" : "status"}
      className={cn("rounded-md border px-3.5 py-2.5 text-sm", KINDS[kind], className)}
    >
      {children}
    </div>
  );
}

export function Loading({ label = "Loading..." }: { label?: string }) {
  return (
    <div className="flex items-center gap-2.5 px-5 py-8 text-sm text-ink-soft" role="status">
      <span aria-hidden className="h-4 w-4 animate-spin rounded-full border-2 border-ledger border-t-transparent" />
      {label}
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="px-5 py-10 text-center">
      <p className="text-sm font-medium text-ink">{title}</p>
      {children ? <div className="mx-auto mt-1 max-w-md text-sm text-ink-soft">{children}</div> : null}
    </div>
  );
}
