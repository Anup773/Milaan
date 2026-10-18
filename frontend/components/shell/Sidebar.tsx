"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { NAV } from "./nav";
import { cn } from "@/lib/utils";

// Small line icons, drawn here so the app needs no icon package.
const ICONS: Record<string, string> = {
  grid: "M3 3h6v6H3zM11 3h6v6h-6zM3 11h6v6H3zM11 11h6v6h-6z",
  book: "M4 3h9a2 2 0 0 1 2 2v12H6a2 2 0 0 1-2-2zM4 15a2 2 0 0 1 2-2h9",
  building: "M4 17V4l7-1v14M11 7h5v10M7 7h1M7 10h1M7 13h1M13 10h1M13 13h1",
  upload: "M10 13V4M6.5 7.5 10 4l3.5 3.5M4 14v2h12v-2",
  link: "M8.5 11.5a3 3 0 0 0 4.2 0l2-2a3 3 0 0 0-4.2-4.2l-.8.8M11.5 8.5a3 3 0 0 0-4.2 0l-2 2a3 3 0 0 0 4.2 4.2l.8-.8",
  compare: "M6 4v12M14 4v12M3 7l3-3 3 3M11 13l3 3 3-3",
  calendar: "M4 5h12v11H4zM4 8h12M7 3v3M13 3v3",
  scale: "M10 3v14M5 17h10M4 7h12M4 7l-2 5a2.5 2.5 0 0 0 4 0zM16 7l-2 5a2.5 2.5 0 0 0 4 0z",
  flag: "M5 17V3M5 4h9l-2 3.5L14 11H5",
  edit: "M4 16l1-4 8.5-8.5 3 3L8 15zM12 5l3 3",
  bolt: "M11 2 4 11h5l-1 7 7-9h-5z",
  wave: "M2 10c2-4 3-4 5 0s3 4 5 0 3-4 6 0",
  check: "M4 10.5 8 14.5 16 5.5",
  shield: "M10 2.5 16 5v5c0 3.5-2.5 6-6 7.5C6.5 16 4 13.5 4 10V5z",
};

function Icon({ name }: { name: string }) {
  return (
    <svg width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d={ICONS[name] ?? ICONS.grid} />
    </svg>
  );
}

export function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  return (
    <nav aria-label="Main" className="flex h-full flex-col gap-5 overflow-y-auto px-3 py-5">
      <Link href="/dashboard" onClick={onNavigate} className="flex items-center gap-2.5 px-2">
        <span className="flex h-8 w-8 items-center justify-center rounded-md bg-ledger text-sm font-bold text-white">M</span>
        <span className="text-lg font-semibold tracking-tight text-ink">Milaan</span>
      </Link>
      {NAV.map((group) => (
        <div key={group.title}>
          <div className="px-2 pb-1.5 text-[11px] font-semibold uppercase tracking-wider text-ink-faint">{group.title}</div>
          <ul className="space-y-0.5">
            {group.items.map((item) => {
              const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    onClick={onNavigate}
                    aria-current={active ? "page" : undefined}
                    className={cn(
                      "flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm font-medium transition-colors",
                      active ? "bg-ledger-soft text-ledger-dark" : "text-ink-soft hover:bg-paper hover:text-ink",
                    )}
                  >
                    <Icon name={item.icon} />
                    {item.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </nav>
  );
}