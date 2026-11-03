
"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, errorMessage } from "./api-client";
import { setDisplayLocale } from "./format";
import type { CountryProfile, PolicyView, StatementTitles } from "./policy-types";
import type { Company, Me, Period } from "./types";

// What the whole dashboard shares: who is signed in, which company's books are open and which period, and how that
// company writes dates and numbers and what it calls its statements (its accounting policy and country).
// The chosen company and period are remembered in this browser (a per-viewer convenience only).

/** The titles used before a company has a policy (the same wording the statements have always used). */
export const DEFAULT_TITLES: StatementTitles = {
  balance_sheet: "Balance sheet",
  profit_and_loss: "Profit & loss",
  cash_flow: "Cash flow",
  changes_in_equity: "Changes in equity",
  trial_balance: "Trial balance",
  profit_label: "Net profit",
  equity_label: "Equity",
};

export interface CompanyLocale {
  /** False until the company's accounting policy is set up: the old behaviour (AD dates, Indian grouping) stays. */
  configured: boolean;
  calendar: "AD" | "BS";
  dateOrder: "DMY" | "MDY";
  grouping: "INDIAN" | "WESTERN";
  rounding: "EXACT" | "WHOLE";
  jurisdiction: string | null;
  currency: string | null;
  country: CountryProfile | null;
  titles: StatementTitles;
}

const DEFAULT_LOCALE: CompanyLocale = {
  configured: false,
  calendar: "AD",
  dateOrder: "DMY",
  grouping: "INDIAN",
  rounding: "EXACT",
  jurisdiction: null,
  currency: null,
  country: null,
  titles: DEFAULT_TITLES,
};

function localeFrom(view: PolicyView | null): CompanyLocale {
  const p = view?.policy;
  if (!view || !p) return DEFAULT_LOCALE;
  return {
    configured: true,
    calendar: p.calendar,
    dateOrder: p.date_order,
    grouping: p.number_grouping,
    rounding: p.statement_rounding,
    jurisdiction: p.jurisdiction,
    currency: p.currency,
    country: view.country,
    titles: view.country?.statements ?? DEFAULT_TITLES,
  };
}

interface Workspace {
  me: Me | null;
  companies: Company[];
  company: Company | null;
  periods: Period[];
  period: Period | null;
  loading: boolean;
  error: string | null;
  /** How the open company writes dates and numbers, and what it calls its statements. */
  locale: CompanyLocale;
  /** Call after the policy is saved so every page follows the new settings. */
  reloadPolicy: () => void;
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
  const [policyView, setPolicyView] = useState<PolicyView | null>(null);
  const [policyTick, setPolicyTick] = useState(0);

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

  // The company's policy decides how its dates and numbers are shown. A failure here is not fatal: the screens just keep
  // the old behaviour (AD dates, Indian grouping) until the policy can be read.
  useEffect(() => {
    if (!companyId) {
      setDisplayLocale(null);
      setPolicyView(null);
      return;
    }
    let alive = true;
    api<PolicyView>(`companies/${companyId}/policy`)
      .then((view) => {
        if (!alive) return;
        const next = localeFrom(view);
        setDisplayLocale({ calendar: next.calendar, grouping: next.grouping });
        setPolicyView(view);
      })
      .catch(() => {
        if (!alive) return;
        setDisplayLocale(null);
        setPolicyView(null);
      });
    return () => {
      alive = false;
    };
  }, [companyId, policyTick]);

  const reloadPolicy = useCallback(() => setPolicyTick((n) => n + 1), []);

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
      locale: localeFrom(policyView),
      reloadPolicy,
      setCompanyId,
      setPeriodId,
      reloadCompanies,
      reloadPeriods,
    }),
    [me, companies, companyId, periods, periodId, loading, error, policyView, reloadPolicy, setCompanyId, setPeriodId, reloadCompanies, reloadPeriods],
  );

  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}

export function useWorkspace(): Workspace {
  const ctx = useContext(WorkspaceContext);
  if (!ctx) throw new Error("useWorkspace must be used inside <WorkspaceProvider>");
  return ctx;
}