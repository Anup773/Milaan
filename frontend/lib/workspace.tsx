"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, errorMessage } from "./api-client";
import type { Company, Me, Period } from "./types";

// What the whole dashboard shares: who is signed in, which company's books are open and which period.
// The chosen company and period are remembered in this browser (a per-viewer convenience only).

interface Workspace {
  me: Me | null;
  companies: Company[];
  company: Company | null;
  periods: Period[];
  period: Period | null;
  loading: boolean;
  error: string | null;
  setCompanyId: (id: string) => void;
  setPeriodId: (id: string) => void;
  reloadCompanies: () => Promise<void>;
  reloadPeriods: () => Promise<void>;
}

const WorkspaceContext = createContext<Workspace | null>(null);

const COMPANY_KEY = "milaan.companyId";
const periodKey = (companyId: string) => `milaan.periodId.${companyId}`;

function readStored(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeStored(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* storage unavailable (private window, blocked) -- the choice just is not remembered */
  }
}

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [companies, setCompanies] = useState<Company[]>([]);
  const [companyId, setCompanyIdState] = useState<string | null>(null);
  const [periods, setPeriods] = useState<Period[]>([]);
  const [periodId, setPeriodIdState] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const pickCompany = useCallback((list: Company[], preferred: string | null) => {
    const chosen = list.find((c) => c.id === preferred) ?? list.find((c) => c.id === readStored(COMPANY_KEY)) ?? list[0] ?? null;
    setCompanyIdState(chosen ? chosen.id : null);
    if (chosen) writeStored(COMPANY_KEY, chosen.id);
  }, []);

  const loadCompanies = useCallback(async () => {
    const result = await api<{ companies: Company[] }>("companies");
    setCompanies(result.companies);
    return result.companies;
  }, []);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const [who, list] = await Promise.all([api<Me>("auth/me"), loadCompanies()]);
        if (!alive) return;
        setMe(who);
        pickCompany(list, null);
      } catch (err) {
        if (alive) setError(errorMessage(err));
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, [loadCompanies, pickCompany]);

  const loadPeriods = useCallback(async (forCompany: string, preferred: string | null) => {
    const result = await api<{ periods: Period[] }>(`companies/${forCompany}/accounting-periods`);
    const sorted = [...result.periods].sort((a, b) => a.period_start.localeCompare(b.period_start));
    setPeriods(sorted);
    const chosen =
      sorted.find((p) => p.id === preferred) ??
      sorted.find((p) => p.id === readStored(periodKey(forCompany))) ??
      sorted[sorted.length - 1] ??
      null;
    setPeriodIdState(chosen ? chosen.id : null);
    if (chosen) writeStored(periodKey(forCompany), chosen.id);
  }, []);

  useEffect(() => {
    if (!companyId) {
      setPeriods([]);
      setPeriodIdState(null);
      return;
    }
    let alive = true;
    loadPeriods(companyId, null).catch((err) => {
      if (alive) setError(errorMessage(err));
    });
    return () => {
      alive = false;
    };
  }, [companyId, loadPeriods]);

  const setCompanyId = useCallback((id: string) => {
    setCompanyIdState(id);
    writeStored(COMPANY_KEY, id);
  }, []);

  const setPeriodId = useCallback(
    (id: string) => {
      setPeriodIdState(id);
      if (companyId) writeStored(periodKey(companyId), id);
    },
    [companyId],
  );

  const reloadCompanies = useCallback(async () => {
    const list = await loadCompanies();
    pickCompany(list, companyId);
  }, [companyId, loadCompanies, pickCompany]);

  const reloadPeriods = useCallback(async () => {
    if (companyId) await loadPeriods(companyId, periodId);
  }, [companyId, periodId, loadPeriods]);

  const value = useMemo<Workspace>(
    () => ({
      me,
      companies,
      company: companies.find((c) => c.id === companyId) ?? null,
      periods,
      period: periods.find((p) => p.id === periodId) ?? null,
      loading,
      error,
      setCompanyId,
      setPeriodId,
      reloadCompanies,
      reloadPeriods,
    }),
    [me, companies, companyId, periods, periodId, loading, error, setCompanyId, setPeriodId, reloadCompanies, reloadPeriods],
  );

  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}

export function useWorkspace(): Workspace {
  const ctx = useContext(WorkspaceContext);
  if (!ctx) throw new Error("useWorkspace must be used inside <WorkspaceProvider>");
  return ctx;
}