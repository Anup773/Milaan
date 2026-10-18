"use client";

import { useState, type ReactNode } from "react";
import { WorkspaceProvider } from "@/lib/workspace";
import { Sidebar } from "@/components/shell/Sidebar";
import { Topbar } from "@/components/shell/Topbar";

export default function DashboardLayout({ children }: { children: ReactNode }) {
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <WorkspaceProvider>
      <div className="min-h-screen lg:grid lg:grid-cols-[15rem_1fr]">
        <aside className="hidden border-r border-rule bg-card lg:block">
          <div className="sticky top-0 h-screen">
            <Sidebar />
          </div>
        </aside>

        {menuOpen ? (
          <div className="fixed inset-0 z-40 lg:hidden" onClick={() => setMenuOpen(false)}>
            <div className="absolute inset-0 bg-ink/40" />
            <aside className="relative h-full w-64 bg-card shadow-xl" onClick={(e) => e.stopPropagation()}>
              <Sidebar onNavigate={() => setMenuOpen(false)} />
            </aside>
          </div>
        ) : null}

        <div className="flex min-w-0 flex-col">
          <Topbar onMenu={() => setMenuOpen(true)} />
          <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 sm:px-6 sm:py-8">{children}</main>
        </div>
      </div>
    </WorkspaceProvider>
  );
}