"""
Nepal: tax depreciation under the Income Tax Act, 2058, Schedule 2 -- pure logic, no database.

How the schedule works (as far as the public text of Schedule 2 read for this phase says; confirm every position with a CA):

  Pools. A: buildings and permanent structures. B: computers, furniture, office equipment. C: automobiles, buses, minibuses.
  D: construction and excavation equipment and other depreciable assets not in A-C. E: intangible assets, each in a pool of its own.

  Pools A to D (declining balance). Depreciation = depreciation base x rate. The base = the pool's balance carried
  from last year (after last year's depreciation) + this year's additions, counted as below, minus disposal proceeds,
  never below zero. Rates: A 5%, B 25%, C 20%, D 15%.

  Timing of additions. An asset bought in the first six months of the fiscal year (Shrawan to Poush) is added at its
  full cost, one bought in Magh to Chaitra at two thirds, one bought in Baisakh to Ashadh at one third. The rest of the cost is added
  in the NEXT year (at full), unless the pool is closed in the meantime.

  Disposals. If the proceeds are more than the pool's balance before the proceeds, the excess is income. When every asset in a pool
  is disposed of during the year the pool is closed: proceeds above (balance + all additions at full cost) is income, a shortfall is a
  deductible loss, and there is no depreciation for that pool that year.

  Small balance. If the depreciation worked out is under Rs 2,000, the whole remaining base may be claimed (done here, and said so).

  Pool E (intangibles). Each intangible is its own pool (any pool code starting with E, such as "E-licence"). Rate = 1 divided
  by the useful life in years, with the life rounded to the nearest half year. Milaan charges that rate on the cost counted so
  far (the same timing rule for the first year), never more than the cost. The source text for E was thin: confirm this
  treatment with the CA.

  Rates. Schedule 2 adds one third to the rates of A to D for powerhouse and public-infrastructure projects (section 19(2));
  that is a company rate you set (Rates), not something the engine decides.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ...calendars import bs
from ...calendars.fiscal import FiscalYear
from .common import (ADDITION, DISPOSAL, HUNDRED, OPENING, ZERO, Movement, RateRow, col, fmt, money, resolve_rate)

POOL_NAMES: Dict[str, str] = {
    "A": "A - Buildings, structures and permanent works",
    "B": "B - Computers, furniture, fixtures and office equipment",
    "C": "C - Automobiles, buses and minibuses",
    "D": "D - Construction and excavation equipment and other depreciable assets",
    "E": "E - Intangible asset",
}
STANDARD_FROM = date(2001, 7, 16)  # Shrawan 1, 2058: the first day of fiscal year 2058/59, the first the Act applied to
STANDARD_RATES: Tuple[RateRow, ...] = tuple(
    RateRow(pool, Decimal(rate), STANDARD_FROM, "Income Tax Act 2058, Schedule 2") for pool, rate in
    (("A", "5"), ("B", "25"), ("C", "20"), ("D", "15")))
# Company rate presets the screen offers (the user still saves them as the company's own rates).
RATE_PRESETS: Tuple[Dict[str, Any], ...] = (
    {"name": "Standard rates (Schedule 2)", "rates": {"A": "5", "B": "25", "C": "20", "D": "15"},
     "note": "Income Tax Act 2058, Schedule 2."},
    {"name": "Powerhouse / public-infrastructure project: one third added", "rates": {"A": "5", "B": "33.33", "C": "26.67", "D": "20"},
     "note": "Section 19(2) projects get one third added to the rates (Schedule 2, 3(2)). These are the rates printed in the Upper "
             "Syange statements (pool A is shown unchanged there; the text says A to D). Confirm with the CA."},
)
SMALL_BALANCE = Decimal("2000")
THIRD = Decimal(1) / Decimal(3)


def is_intangible(pool: str) -> bool:
    return pool.upper().startswith("E")


def timing_thirds(fy: FiscalYear, d: date) -> int:
    """3, 2 or 1: how many thirds of an addition's cost count in the year it is bought (months counted in BS from the year's start)."""
    start_b = bs.ad_to_bs(fy.start)
    b = bs.ad_to_bs(d)
    months = (b.year - start_b.year) * 12 + (b.month - start_b.month)
    if not 0 <= months <= 11:
        raise ValueError(f"{d.isoformat()} is outside the fiscal year {fy.label}")
    return 3 if months <= 5 else 2 if months <= 8 else 1


def half_year_life(years: Decimal) -> Decimal:
    """A useful life rounded to the nearest half year (halves up), as Schedule 2 prescribes for pool E."""
    if years <= 0:
        raise ValueError("the useful life must be more than zero years")
    return (years * 2).quantize(Decimal("1"), rounding=ROUND_HALF_UP) / 2


@dataclass
class PoolState:
    """What a pool carries from one year to the next."""
    wdv: Decimal = ZERO            # the balance after last year's depreciation (A-D); for E: cost counted so far less depreciation
    deferred: Decimal = ZERO       # cost still to be added in the coming year
    life_years: Optional[Decimal] = None   # pool E
    counted_cost: Decimal = ZERO   # pool E: cost counted so far
    accumulated: Decimal = ZERO    # pool E: depreciation so far


def _fraction_counted(cost: Decimal, thirds: int) -> Decimal:
    return money(cost * thirds / 3)


def compute_year(state: Mapping[str, PoolState], movements: Sequence[Movement], fy: FiscalYear,
                 company_rates: Sequence[RateRow] = (), claim_small_balance: bool = True
                 ) -> Tuple[List[Dict[str, Any]], Dict[str, PoolState]]:
    """
    One fiscal year of the schedule. `state` is each pool's carry-in; `movements` are this year's additions and disposals
    (an OPENING movement is applied by the caller before this). Returns (one row per pool, the carry-out state).
    """
    pools = sorted(set(state) | {m.pool for m in movements})
    rows: List[Dict[str, Any]] = []
    out: Dict[str, PoolState] = {}
    for pool in pools:
        mine = [m for m in movements if m.pool == pool]
        st = state.get(pool, PoolState())
        if is_intangible(pool):
            row, new = _intangible(pool, st, mine, fy, company_rates)
        else:
            row, new = _declining(pool, st, mine, fy, company_rates, claim_small_balance)
        rows.append(row)
        out[pool] = new
    return rows, out


def _rate(pool: str, fy: FiscalYear, company_rates: Sequence[RateRow], key: Optional[str] = None) -> RateRow:
    return resolve_rate(key or pool, fy.end, company_rates, STANDARD_RATES)


def _declining(pool: str, st: PoolState, mine: Sequence[Movement], fy: FiscalYear, company_rates, claim_small: bool):
    rate_row = _rate(pool, fy, company_rates)
    rate = rate_row.rate
    additions = [m for m in mine if m.kind == ADDITION]
    disposals = [m for m in mine if m.kind == DISPOSAL]
    cost_full = sum((m.amount for m in additions), ZERO)
    counted = sum((_fraction_counted(m.amount, timing_thirds(fy, m.event_date)) for m in additions), ZERO)
    deferred_out = cost_full - counted
    proceeds = sum((m.amount for m in disposals), ZERO)
    dissolves = any(bool(m.details.get("dissolves_pool")) for m in disposals)
    notes: List[str] = []

    opening = st.wdv
    carried_in = st.deferred
    before_proceeds = opening + carried_in + counted
    gain = loss = depreciation = ZERO

    if dissolves:
        everything = opening + carried_in + cost_full
        if proceeds > everything:
            gain = proceeds - everything
        else:
            loss = everything - proceeds
        base = closing = deferred_out = ZERO
        notes.append("Every asset in the pool was disposed of, so the pool is closed: proceeds above the balance and all additions "
                     "at full cost is income, a shortfall is a deductible loss, and there is no depreciation this year.")
    else:
        if proceeds > before_proceeds:
            gain = proceeds - before_proceeds
            base = ZERO
            notes.append("Disposal proceeds are more than the pool's balance, so the excess is income.")
        else:
            base = before_proceeds - proceeds
        depreciation = money(base * rate / HUNDRED)
        if claim_small and ZERO < depreciation < SMALL_BALANCE and base > 0:
            depreciation = base
            notes.append(f"The depreciation worked out was under Rs {SMALL_BALANCE:,.0f}, so the whole remaining base is claimed.")
        closing = base - depreciation
    if deferred_out > 0:
        notes.append(f"{fmt(deferred_out)} of this year's additions is added next year (only part of the cost counts in the year bought).")
    row = {
        "pool": pool, "name": POOL_NAMES.get(pool, pool), "rate": fmt(rate), "rate_source": rate_row.source,
        "opening": fmt(opening), "carried_in": fmt(carried_in), "additions_full": fmt(cost_full), "additions_counted": fmt(counted),
        "deferred_out": fmt(deferred_out), "disposals": fmt(proceeds), "base": fmt(base), "depreciation": fmt(depreciation),
        "closing": fmt(closing), "income_from_disposal": fmt(gain), "loss_on_disposal": fmt(loss), "notes": notes,
    }
    return row, PoolState(wdv=closing, deferred=deferred_out)


def _intangible(pool: str, st: PoolState, mine: Sequence[Movement], fy: FiscalYear, company_rates):
    additions = [m for m in mine if m.kind == ADDITION]
    disposals = [m for m in mine if m.kind == DISPOSAL]
    life = st.life_years
    for m in additions:
        raw = m.details.get("life_years")
        if raw is None:
            raise ValueError(f"pool {pool}: an intangible asset needs its useful life in years (details: life_years)")
        this_life = half_year_life(Decimal(str(raw)))
        if life is not None and this_life != life:
            raise ValueError(f"pool {pool}: two additions have different lives ({life} and {this_life} years); Schedule 2 puts each "
                             "intangible in a pool of its own, so give each its own pool code (for example E-licence, E-software)")
        life = this_life
    if life is None:
        raise ValueError(f"pool {pool}: no useful life is known (an addition with life_years is needed)")
    own = [r for r in company_rates if r.pool == pool and r.effective_from <= fy.end]
    rate_row = max(own, key=lambda r: r.effective_from) if own else None
    rate = rate_row.rate if rate_row is not None else HUNDRED / life

    cost_full = sum((m.amount for m in additions), ZERO)
    counted_new = sum((_fraction_counted(m.amount, timing_thirds(fy, m.event_date)) for m in additions), ZERO)
    deferred_out = cost_full - counted_new
    counted_total = st.counted_cost + st.deferred + counted_new       # cost counted so far, including last year's carry
    proceeds = sum((m.amount for m in disposals), ZERO)
    opening = st.counted_cost - st.accumulated
    notes: List[str] = []
    gain = loss = depreciation = base = closing = ZERO
    accumulated = st.accumulated

    if disposals:
        remaining = counted_total + deferred_out - accumulated   # undepreciated cost, with all additions at full cost
        gain, loss = (proceeds - remaining, ZERO) if proceeds > remaining else (ZERO, remaining - proceeds)
        counted_total = accumulated = deferred_out = ZERO
        notes.append("The intangible was disposed of: proceeds above its undepreciated cost is income, a shortfall is a deductible loss.")
    else:
        base = counted_total - accumulated
        depreciation = min(money(counted_total * rate / HUNDRED), base)
        accumulated += depreciation
        closing = base - depreciation
    if deferred_out > 0:
        notes.append(f"{fmt(deferred_out)} of this year's additions is counted next year.")
    row = {
        "pool": pool, "name": POOL_NAMES["E"] + (f" ({pool})" if pool.upper() != "E" else ""), "rate": fmt(money(rate)),
        "rate_source": "company" if rate_row is not None else f"1 / {life} years",
        "opening": fmt(opening), "carried_in": fmt(st.deferred), "additions_full": fmt(cost_full), "additions_counted": fmt(counted_new),
        "deferred_out": fmt(deferred_out), "disposals": fmt(proceeds), "base": fmt(base), "depreciation": fmt(depreciation),
        "closing": fmt(closing), "income_from_disposal": fmt(gain), "loss_on_disposal": fmt(loss), "notes": notes,
    }
    return row, PoolState(wdv=closing, deferred=deferred_out, life_years=life, counted_cost=counted_total, accumulated=accumulated)


COLUMNS = [
    col("pool", "Pool", False), col("rate", "Rate %", False), col("opening", "Opening balance"), col("carried_in", "Added from last year"),
    col("additions_full", "Additions (cost)"), col("additions_counted", "Additions counted this year"), col("disposals", "Disposal proceeds"),
    col("base", "Depreciation base"), col("depreciation", "Depreciation"), col("closing", "Closing balance"),
    col("income_from_disposal", "Income from disposal"), col("loss_on_disposal", "Loss on disposal"),
]


def totals(rows: Sequence[Mapping[str, Any]]) -> Dict[str, str]:
    keys = ("opening", "carried_in", "additions_full", "additions_counted", "deferred_out", "disposals", "base", "depreciation",
            "closing", "income_from_disposal", "loss_on_disposal")
    return {k: fmt(sum((Decimal(r[k]) for r in rows), ZERO)) for k in keys}