"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { useWorkspace } from "@/lib/workspace";
import { Card } from "@/components/ui/card";
import { Loading, Notice } from "@/components/common/notice";
import type { Company, Period } from "@/lib/types";
import type { Role } from "@/lib/roles";

/** Shows its children only once a company (and, if asked, a period) is chosen; otherwise says what to do first. */
export function Gate({
  needsPeriod = false,
  children,
}: {
  needsPeriod?: boolean;
  children: (ctx: { company: Company; period: Period | null; role: Role }) => ReactNode;
}) {
  const { company, period, loading, error, me } = useWorkspace();

  if (loading) return <Loading label="Opening your workspace..." />;
  if (error) return <Notice kind="error">{error}</Notice>;
  if (!me) return <Notice kind="error">could not tell who is signed in</Notice>;
  if (!company) {
    return (
      <Card className="px-5 py-10 text-center">
        <p className="text-sm font-medium text-ink">No company yet</p>
        <p className="mx-auto mt-1 max-w-md text-sm text-ink-soft">
          Add the first company on the{" "}
          <Link className="font-medium text-ledger underline" href="/companies">
            Companies
          </Link>{" "}
          page.
        </p>
      </Card>
    );
  }
  if (needsPeriod && !period) {
    return (
      <Card className="px-5 py-10 text-center">
        <p className="text-sm font-medium text-ink">{company.name} has no accounting period yet</p>
        <p className="mx-auto mt-1 max-w-md text-sm text-ink-soft">
          Create one on the{" "}
          <Link className="font-medium text-ledger underline" href="/imports">
            Imports
          </Link>{" "}
          page (under "Accounting periods"), then come back.
        </p>
      </Card>
    );
  }
  return <>{children({ company, period, role: me.role })}</>;
}