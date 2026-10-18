import { formatDelta, formatMoney, signOf } from "@/lib/format";
import { cn } from "@/lib/utils";

/** An exact decimal string shown with Indian grouping and tabular numerals. */
export function Money({ value, className }: { value: string | null | undefined; className?: string }) {
  return <span className={cn("num whitespace-nowrap", className)}>{formatMoney(value)}</span>;
}

/** A change: +green / -red / 0 neutral. `goodWhen` says which direction is good news ("up" for profit, "down" for expense). */
export function Delta({
  value,
  goodWhen = "up",
  className,
}: {
  value: string | null | undefined;
  goodWhen?: "up" | "down" | "neutral";
  className?: string;
}) {
  const sign = signOf(value);
  let tone = "text-ink-soft";
  if (sign !== 0 && goodWhen !== "neutral") {
    const good = (sign > 0 && goodWhen === "up") || (sign < 0 && goodWhen === "down");
    tone = good ? "text-pass" : "text-fail";
  }
  return <span className={cn("num whitespace-nowrap font-medium", tone, className)}>{formatDelta(value)}</span>;
}