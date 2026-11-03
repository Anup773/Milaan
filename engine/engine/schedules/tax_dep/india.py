"""
India: income tax depreciation on blocks of assets at written-down value -- pure logic, no database.

How it works (Income-tax Act, 1961, section 32 and Appendix I of the Income-tax Rules; for tax years from 2026-27 the
Income-tax Act, 2025 applies, and the sources read say the categories and rates carry over: confirm with the CA):

  Blocks. Assets of the same class and rate form a block. Depreciation is on the block's written-down value (WDV), not asset by asset.
  Rates (main blocks): buildings 5% residential, 10% other, 40% purely temporary; furniture 10%; plant and machinery 15%
  (motor cars 15%, vehicles on hire 30%); computers including software 40%; intangible assets 25%.

  Half-rate rule. An addition put to use for LESS than 180 days in the year gets half the rate in that year.

  Sales. Sale proceeds reduce the block. If the proceeds are more than the block's WDV plus additions, the excess is a short-term
  capital gain (the block is then nil). If every asset in the block is sold (the block ceases) and some WDV is left, that is a
  short-term capital loss.

  Not built: additional depreciation (20% on new plant in manufacturing), depreciation on assets of a different rate class in one
  block, and the Companies Act Schedule II book depreciation (that is the book schedule).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Mapping, Sequence, Tuple

from ...calendars.fiscal import FiscalYear
from .common import ADDITION, DISPOSAL, HUNDRED, ZERO, Movement, RateRow, col, fmt, money, resolve_rate

BLOCKS: Dict[str, str] = {
    "BLDG_RES": "Buildings: residential (not hotels or boarding houses)",
    "BLDG_OTHER": "Buildings: other than residential",
    "BLDG_TEMP": "Buildings: purely temporary erections",
    "FURNITURE": "Furniture and fittings",
    "PLANT": "Plant and machinery (general)",
    "CAR": "Motor cars (not on hire)",
    "VEHICLE_HIRE": "Motor buses, lorries and taxis on hire",
    "COMPUTER": "Computers including software",
    "INTANGIBLE": "Intangible assets (know-how, patents, licences, franchises)",
}
STANDARD_FROM = date(2017, 4, 1)  # rates in this table are those in force from the 2017-18 year
STANDARD_RATES: Tuple[RateRow, ...] = tuple(
    RateRow(code, Decimal(rate), STANDARD_FROM, "Income-tax Rules, Appendix I (main blocks)") for code, rate in (
        ("BLDG_RES", "5"), ("BLDG_OTHER", "10"), ("BLDG_TEMP", "40"), ("FURNITURE", "10"), ("PLANT", "15"), ("CAR", "15"),
        ("VEHICLE_HIRE", "30"), ("COMPUTER", "40"), ("INTANGIBLE", "25")))
RATE_PRESETS: Tuple[Dict[str, Any], ...] = (
    {"name": "Standard rates (main blocks)", "rates": {r.pool: str(r.rate) for r in STANDARD_RATES},
     "note": "Appendix I of the Income-tax Rules. Check the rate for your block before filing."},
)
HALF_RATE_DAYS = 180


def days_used(d: date, fy: FiscalYear) -> int:
    """Days from the date the asset was put to use to the end of the year, both included."""
    return (fy.end - d).days + 1


def compute_year(state: Mapping[str, Decimal], movements: Sequence[Movement], fy: FiscalYear,
                 company_rates: Sequence[RateRow] = ()) -> Tuple[List[Dict[str, Any]], Dict[str, Decimal]]:
    """One fiscal year. `state` is each block's written-down value carried in. Returns (rows, carry-out)."""
    blocks = sorted(set(state) | {m.pool for m in movements})
    rows: List[Dict[str, Any]] = []
    out: Dict[str, Decimal] = {}
    for block in blocks:
        mine = [m for m in movements if m.pool == block]
        rate_row = resolve_rate(block, fy.end, company_rates, STANDARD_RATES)
        rate = rate_row.rate
        opening = state.get(block, ZERO)
        adds = [m for m in mine if m.kind == ADDITION]
        full = sum((m.amount for m in adds if days_used(m.event_date, fy) >= HALF_RATE_DAYS), ZERO)
        half = sum((m.amount for m in adds if days_used(m.event_date, fy) < HALF_RATE_DAYS), ZERO)
        disposals = [m for m in mine if m.kind == DISPOSAL]
        proceeds = sum((m.amount for m in disposals), ZERO)
        ceases = any(bool(m.details.get("block_ceases")) for m in disposals)
        notes: List[str] = []
        stcg = stcl = depreciation = ZERO

        wdv_total = opening + full + half
        if ceases:
            if proceeds > wdv_total:
                stcg = proceeds - wdv_total
            else:
                stcl = wdv_total - proceeds
            base_full = base_half = closing = ZERO
            notes.append("Every asset in the block was sold, so the block ceases: proceeds above its value is a short-term capital gain, "
                         "a shortfall is a short-term capital loss, and there is no depreciation this year.")
        else:
            base_full_pre = opening + full
            if proceeds <= base_full_pre:
                base_full, left = base_full_pre - proceeds, ZERO
            else:
                base_full, left = ZERO, proceeds - base_full_pre
            base_half = max(ZERO, half - left)
            stcg = max(ZERO, left - half)
            if stcg > 0:
                notes.append("Sale proceeds are more than the block's value, so the excess is a short-term capital gain and the block is nil.")
            depreciation = money(base_full * rate / HUNDRED) + money(base_half * rate / HUNDRED / 2)
            closing = base_full + base_half - depreciation
        if half > 0:
            notes.append(f"{fmt(half)} of additions was used for under {HALF_RATE_DAYS} days, so it gets half the rate.")
        rows.append({
            "pool": block, "name": BLOCKS.get(block, block), "rate": fmt(rate), "rate_source": rate_row.source,
            "opening": fmt(opening), "additions_full_rate": fmt(full), "additions_half_rate": fmt(half), "disposals": fmt(proceeds),
            "base": fmt(base_full + base_half), "depreciation": fmt(depreciation), "closing": fmt(closing),
            "short_term_gain": fmt(stcg), "short_term_loss": fmt(stcl), "notes": notes,
        })
        out[block] = closing
    return rows, out


COLUMNS = [
    col("pool", "Block", False), col("rate", "Rate %", False), col("opening", "Opening WDV"),
    col("additions_full_rate", "Additions (180 days or more)"), col("additions_half_rate", "Additions (under 180 days)"),
    col("disposals", "Sale proceeds"), col("base", "Value for depreciation"), col("depreciation", "Depreciation"),
    col("closing", "Closing WDV"), col("short_term_gain", "Short-term capital gain"), col("short_term_loss", "Short-term capital loss"),
]


def totals(rows: Sequence[Mapping[str, Any]]) -> Dict[str, str]:
    keys = ("opening", "additions_full_rate", "additions_half_rate", "disposals", "base", "depreciation", "closing",
            "short_term_gain", "short_term_loss")
    return {k: fmt(sum((Decimal(r[k]) for r in rows), ZERO)) for k in keys}