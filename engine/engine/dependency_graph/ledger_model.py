"""
Builds the dependency graph for one company + accounting period from the
REAL ledger -- read-only, nothing is written. Same data and the same
signed-balance rule (ledger.money.signed_balance) as ledger/reports.py,
using the same two scopes reports.py uses:

  * "period"     -- journal entries whose accounting_period_id is this
                    period (what the Trial Balance and P&L use).
  * "cumulative" -- every entry dated on/before the period's end (what
                    the Balance Sheet uses).

Graph shape (leaves at the top, statements at the bottom):

  acct:<id>:period / acct:<id>:cum      one per account (period only for
                                         Income/Expense accounts)
  schedule:fixed_asset:<asset_id>        depreciation actually POSTED this
                                         period; feeds the expense account
                                         (debit) and the accumulated
                                         depreciation account (credit)
  pl:total_income, pl:total_expense, pl:net_profit
  bs:total_assets, bs:total_liabilities, bs:total_equity,
  bs:cum_income, bs:cum_expense, bs:retained_earnings,
  bs:check                               Assets - Liabilities - Equity -
                                         Retained earnings; 0 when balanced

An account fed by a schedule is a computed node: "other postings" (a leaf
= ledger balance minus the schedule's share) plus the schedule node(s) --
so at baseline it equals the ledger exactly, and changing a schedule
figure flows to BOTH sides of the double entry (expense up, accumulated
depreciation up), keeping bs:check at zero. Depreciation that has not
been posted yet is not in the ledger, so it is not in this graph.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Tuple

from ..ledger.money import NormalBalance, normal_balance, signed_balance
from ..ledger.reports import _period_dates
from .registry import GraphModel, NodeSpec

ZERO = Decimal("0.00")
INCOME_EXPENSE = ("Income", "Expense")


def _coefficient(account_type: str, side: str) -> int:
    """How a posting of `side` ('debit'/'credit') moves this account's signed balance."""
    debit_normal = normal_balance(account_type) is NormalBalance.DEBIT
    if side == "debit":
        return 1 if debit_normal else -1
    return -1 if debit_normal else 1


def build_ledger_model(conn, company_id: str, period_id: str) -> GraphModel:
    period_start, period_end, period_label = _period_dates(conn, company_id, period_id)

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT a.id, a.code, a.name, a.account_type,
                   COALESCE(SUM(jl.debit)  FILTER (WHERE je.accounting_period_id = %(p)s), 0),
                   COALESCE(SUM(jl.credit) FILTER (WHERE je.accounting_period_id = %(p)s), 0),
                   COALESCE(SUM(jl.debit)  FILTER (WHERE je.entry_date <= %(end)s), 0),
                   COALESCE(SUM(jl.credit) FILTER (WHERE je.entry_date <= %(end)s), 0)
            FROM accounts a
            LEFT JOIN journal_lines jl ON jl.account_id = a.id
            LEFT JOIN journal_entries je ON je.id = jl.journal_entry_id AND je.company_id = %(c)s
            WHERE a.company_id = %(c)s
            GROUP BY a.id, a.code, a.name, a.account_type
            ORDER BY a.code
            """,
            {"c": company_id, "p": period_id, "end": period_end},
        )
        account_rows = cur.fetchall()

        cur.execute(
            """
            SELECT fa.id, fa.name, fa.depreciation_expense_account_id,
                   fa.accumulated_depreciation_account_id, fade.amount, fade.journal_entry_id
            FROM fixed_asset_depreciation_entries fade
            JOIN fixed_assets fa ON fa.id = fade.fixed_asset_id
            WHERE fade.company_id = %s AND fade.accounting_period_id = %s
            ORDER BY fa.name, fa.id
            """,
            (company_id, period_id),
        )
        schedule_rows = cur.fetchall()

    accounts: Dict[str, Dict[str, Any]] = {}
    for aid, code, name, atype, pd, pc, cd, cc in account_rows:
        accounts[str(aid)] = {
            "id": str(aid), "code": code, "name": name, "type": atype,
            "period": signed_balance(atype, pd, pc), "cum": signed_balance(atype, cd, cc),
            "has_period": (pd != 0 or pc != 0) and atype in INCOME_EXPENSE,
            "has_cum": cd != 0 or cc != 0,
        }

    # (account_id, scope) -> [(schedule_node_id, coefficient, posted_amount)]
    feeds: Dict[Tuple[str, str], List[Tuple[str, int, Decimal]]] = {}
    specs: List[NodeSpec] = []
    for fa_id, fa_name, exp_acc, acc_acc, amount, je_id in schedule_rows:
        exp_acc, acc_acc = str(exp_acc), str(acc_acc)
        node_id = f"schedule:fixed_asset:{fa_id}"
        specs.append(NodeSpec(
            id=node_id, label=f"Depreciation posted - {fa_name}", kind="schedule", value=amount,
            meta={"fixed_asset_id": str(fa_id), "asset_name": fa_name, "journal_entry_id": str(je_id)},
        ))
        for acc_id, side in ((exp_acc, "debit"), (acc_acc, "credit")):
            account = accounts.get(acc_id)
            if account is None:
                continue
            coeff = _coefficient(account["type"], side)
            feeds.setdefault((acc_id, "cum"), []).append((node_id, coeff, amount))
            if account["has_period"]:
                feeds.setdefault((acc_id, "period"), []).append((node_id, coeff, amount))

    def add_account_node(account: Dict[str, Any], scope: str) -> str:
        node_id = f"acct:{account['id']}:{scope}"
        scope_label = "period" if scope == "period" else "cumulative"
        label = f"{account['code']} {account['name']} ({scope_label})"
        meta = {"account_id": account["id"], "code": account["code"], "name": account["name"],
                "account_type": account["type"], "scope": scope_label}
        balance = account[scope]
        fed = feeds.get((account["id"], scope))
        if not fed:
            specs.append(NodeSpec(id=node_id, label=label, kind="ledger", value=balance, meta=meta))
        else:
            other_id = f"{node_id}:other"
            other_value = balance - sum((c * amt for _, c, amt in fed), ZERO)
            specs.append(NodeSpec(
                id=other_id, label=f"{label} - postings not from a schedule", kind="ledger",
                value=other_value, meta={**meta, "other_postings": True},
            ))
            specs.append(NodeSpec(
                id=node_id, label=label, kind="ledger", formula="linear",
                inputs=(other_id, *[s for s, _, _ in fed]),
                params={"coefficients": [1, *[c for _, c, _ in fed]]}, meta=meta,
            ))
        return node_id

    period_nodes: Dict[str, List[str]] = {t: [] for t in INCOME_EXPENSE}
    cum_nodes: Dict[str, List[str]] = {t: [] for t in ("Asset", "Liability", "Equity", "Income", "Expense")}
    for account in accounts.values():  # already ordered by account code
        if account["has_period"]:
            period_nodes[account["type"]].append(add_account_node(account, "period"))
        if account["has_cum"]:
            cum_nodes[account["type"]].append(add_account_node(account, "cum"))

    def computed(node_id, label, kind, formula, inputs, params=None):
        specs.append(NodeSpec(id=node_id, label=label, kind=kind, formula=formula,
                              inputs=tuple(inputs), params=params or {}))

    computed("pl:total_income", f"Total income ({period_label})", "statement", "sum", period_nodes["Income"])
    computed("pl:total_expense", f"Total expense ({period_label})", "statement", "sum", period_nodes["Expense"])
    computed("pl:net_profit", f"Net profit ({period_label})", "statement", "difference",
             ["pl:total_income", "pl:total_expense"])

    as_of = period_end.isoformat()
    computed("bs:total_assets", f"Total assets (as of {as_of})", "statement", "sum", cum_nodes["Asset"])
    computed("bs:total_liabilities", f"Total liabilities (as of {as_of})", "statement", "sum", cum_nodes["Liability"])
    computed("bs:total_equity", f"Total equity (as of {as_of})", "statement", "sum", cum_nodes["Equity"])
    computed("bs:cum_income", f"Cumulative income (to {as_of})", "statement", "sum", cum_nodes["Income"])
    computed("bs:cum_expense", f"Cumulative expense (to {as_of})", "statement", "sum", cum_nodes["Expense"])
    computed("bs:retained_earnings", f"Retained earnings (to {as_of})", "statement", "difference",
             ["bs:cum_income", "bs:cum_expense"])
    computed("bs:check", "Balance check: assets - liabilities - equity - retained earnings (0 = balanced)",
             "check", "linear",
             ["bs:total_assets", "bs:total_liabilities", "bs:total_equity", "bs:retained_earnings"],
             {"coefficients": [1, -1, -1, -1]})

    return GraphModel(specs)
