"""
Database-facing half of the fixed-asset schedule. fixed_assets.py is pure
math; this module loads real assets from Postgres, calls that math, and
either just reports it (rollforward) or actually posts journal entries
(post_depreciation) -- same split as mapping/planner.py + repository.py.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from .fixed_assets import FixedAsset, compute_period_depreciation

ZERO = Decimal("0.00")


def _load_period(conn, company_id: str, period_id: str) -> Tuple[Any, Any]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT period_start, period_end FROM accounting_periods WHERE company_id = %s AND id = %s",
            (company_id, period_id),
        )
        row = cur.fetchone()
    if row is None:
        raise ValueError(f"accounting period {period_id} not found for company {company_id}")
    return row


def _load_assets(conn, company_id: str) -> List[Dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, name, acquisition_date, cost, salvage_value, useful_life_months,
                   disposed_date, asset_account_id, accumulated_depreciation_account_id,
                   depreciation_expense_account_id
            FROM fixed_assets WHERE company_id = %s ORDER BY acquisition_date, name
            """,
            (company_id,),
        )
        rows = cur.fetchall()

    assets = []
    for (aid, name, acq, cost, salvage, life, disposed, asset_acc, accum_acc, exp_acc) in rows:
        assets.append({
            "asset": FixedAsset(
                id=str(aid), name=name, acquisition_date=acq, cost=cost,
                salvage_value=salvage, useful_life_months=life, disposed_date=disposed,
            ),
            "asset_account_id": str(asset_acc),
            "accumulated_depreciation_account_id": str(accum_acc),
            "depreciation_expense_account_id": str(exp_acc),
        })
    return assets


def _accumulated_before(conn, fixed_asset_id: str, period_start) -> Decimal:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COALESCE(SUM(fade.amount), 0)
            FROM fixed_asset_depreciation_entries fade
            JOIN accounting_periods ap ON ap.id = fade.accounting_period_id
            WHERE fade.fixed_asset_id = %s AND ap.period_start < %s
            """,
            (fixed_asset_id, period_start),
        )
        return cur.fetchone()[0]


def rollforward(conn, company_id: str, period_id: str) -> Dict[str, Any]:
    """
    Read-only: opening WDV (written-down value = cost minus accumulated
    depreciation), this period's computed depreciation, and closing WDV,
    for every fixed asset -- whether or not that depreciation has
    actually been posted yet. Posting happens separately
    (post_depreciation), so a CA can review the numbers here first.
    """
    period_start, period_end = _load_period(conn, company_id, period_id)
    assets = _load_assets(conn, company_id)

    lines = []
    for item in assets:
        asset = item["asset"]
        accumulated_before = _accumulated_before(conn, asset.id, period_start)
        opening_wdv = asset.cost - accumulated_before
        this_period = compute_period_depreciation(asset, period_start, period_end, accumulated_before)
        lines.append({
            "fixed_asset_id": asset.id, "name": asset.name,
            "cost": asset.cost, "accumulated_before_period": accumulated_before,
            "opening_wdv": opening_wdv, "depreciation_this_period": this_period,
            "closing_wdv": opening_wdv - this_period,
        })

    return {"period_id": period_id, "period_start": period_start, "period_end": period_end, "assets": lines}


def post_depreciation(conn, *, company_id: str, period_id: str, created_by: Optional[str]) -> Dict[str, Any]:
    """
    Posts one balanced journal entry per asset (Dr depreciation expense,
    Cr accumulated depreciation) for whatever this period's rollforward
    computes. Posts nothing for an asset with zero computed depreciation
    for this period (never a zero-amount line -- migration 0002's check
    constraint would reject one anyway). Idempotent per asset+period via
    fixed_asset_depreciation_entries' UNIQUE constraint: re-running this
    after confirming more assets, or simply retrying, changes nothing for
    an asset already posted this period.
    """
    period_start, period_end = _load_period(conn, company_id, period_id)
    assets = _load_assets(conn, company_id)

    posted, already_posted, skipped_zero = [], [], []

    with conn.cursor() as cur:
        for item in assets:
            asset = item["asset"]
            cur.execute(
                "SELECT amount FROM fixed_asset_depreciation_entries WHERE fixed_asset_id = %s AND accounting_period_id = %s",
                (asset.id, period_id),
            )
            existing = cur.fetchone()
            if existing is not None:
                already_posted.append({"fixed_asset_id": asset.id, "name": asset.name, "amount": existing[0]})
                continue

            accumulated_before = _accumulated_before(conn, asset.id, period_start)
            amount = compute_period_depreciation(asset, period_start, period_end, accumulated_before)
            if amount <= ZERO:
                skipped_zero.append({"fixed_asset_id": asset.id, "name": asset.name})
                continue

            cur.execute(
                """
                INSERT INTO journal_entries (company_id, accounting_period_id, entry_date, description, created_by)
                VALUES (%s, %s, %s, %s, %s) RETURNING id
                """,
                (company_id, period_id, period_end, f"Depreciation - {asset.name}", created_by),
            )
            journal_entry_id = cur.fetchone()[0]

            cur.execute(
                "INSERT INTO journal_lines (company_id, journal_entry_id, account_id, debit, credit) VALUES (%s, %s, %s, %s, 0)",
                (company_id, journal_entry_id, item["depreciation_expense_account_id"], amount),
            )
            cur.execute(
                "INSERT INTO journal_lines (company_id, journal_entry_id, account_id, debit, credit) VALUES (%s, %s, %s, 0, %s)",
                (company_id, journal_entry_id, item["accumulated_depreciation_account_id"], amount),
            )
            cur.execute(
                """
                INSERT INTO fixed_asset_depreciation_entries
                    (company_id, fixed_asset_id, accounting_period_id, journal_entry_id, amount)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (company_id, asset.id, period_id, journal_entry_id, amount),
            )
            posted.append({
                "fixed_asset_id": asset.id, "name": asset.name, "amount": amount,
                "journal_entry_id": str(journal_entry_id),
            })

    return {"period_id": period_id, "posted": posted, "already_posted": already_posted, "skipped_zero": skipped_zero}


def reconcile_against_ledger(conn, company_id: str, period_id: str) -> Dict[str, Any]:
    """
    For each asset's accumulated-depreciation account: compares what the
    schedule says has accumulated (everything posted so far, up to and
    including this period) against that account's actual balance in the
    ledger, as of this period's end -- ARCHITECTURE.md §7/§11's "fixed-asset
    schedule's rollforward checked against the ledger's actual account
    balances", built for real.

    Assets that share one accumulated-depreciation account are added
    together FIRST and the sum is compared to the account once. (Comparing
    each asset on its own against the whole account would report a false
    mismatch for every asset in any company that keeps a single
    "Accumulated Depreciation" account -- the normal case.) Each row still
    shows the asset's own schedule figure; `account_schedule_total` is the
    sum that is actually compared, and `matches` is that comparison.

    Deliberately computed as raw (credit - debit), not via
    money.signed_balance(): the schedule tracks a positive magnitude
    ("how much has accumulated"), while signed_balance's Asset-type
    convention would report this contra-asset balance as negative. Both
    are internally consistent; mixing them would make a correct match
    look like a mismatch over a sign, not a real discrepancy.
    """
    _, period_end = _load_period(conn, company_id, period_id)
    assets = _load_assets(conn, company_id)

    own_total: Dict[Any, Decimal] = {}
    account_total: Dict[str, Decimal] = {}
    assets_on_account: Dict[str, int] = {}
    ledger_balance: Dict[str, Decimal] = {}

    with conn.cursor() as cur:
        for item in assets:
            asset = item["asset"]
            cur.execute(
                """
                SELECT COALESCE(SUM(fade.amount), 0)
                FROM fixed_asset_depreciation_entries fade
                JOIN accounting_periods ap ON ap.id = fade.accounting_period_id
                WHERE fade.fixed_asset_id = %s AND ap.period_end <= %s
                """,
                (asset.id, period_end),
            )
            total = cur.fetchone()[0]
            account_id = str(item["accumulated_depreciation_account_id"])
            own_total[asset.id] = total
            account_total[account_id] = account_total.get(account_id, ZERO) + total
            assets_on_account[account_id] = assets_on_account.get(account_id, 0) + 1

        for account_id in account_total:
            cur.execute(
                """
                SELECT COALESCE(SUM(jl.credit), 0) - COALESCE(SUM(jl.debit), 0)
                FROM journal_lines jl
                JOIN journal_entries je ON je.id = jl.journal_entry_id
                WHERE je.company_id = %s AND jl.account_id = %s AND je.entry_date <= %s
                """,
                (company_id, account_id, period_end),
            )
            ledger_balance[account_id] = cur.fetchone()[0]

    results = []
    for item in assets:
        asset = item["asset"]
        account_id = str(item["accumulated_depreciation_account_id"])
        results.append({
            "fixed_asset_id": asset.id, "name": asset.name,
            "schedule_accumulated_depreciation": own_total[asset.id],
            "assets_sharing_account": assets_on_account[account_id],
            "account_schedule_total": account_total[account_id],
            "ledger_accumulated_depreciation_account_balance": ledger_balance[account_id],
            "matches": account_total[account_id] == ledger_balance[account_id],
        })

    return {"period_id": period_id, "as_of": period_end, "assets": results}
