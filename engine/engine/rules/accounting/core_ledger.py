"""
The double-entry controls Milaan already enforces, whatever the accounting framework. These are not a standard's
requirements; they are the arithmetic every framework assumes, so the set applies everywhere (INTL / ANY).
"""
from __future__ import annotations

from ..registry import ACTIVE, ANY_FRAMEWORK, FULL, INTERNATIONAL, PARTIAL, RuleSet, item, register_rule_set

register_rule_set(RuleSet(
    id="core-ledger",
    family="accounting",
    title="Core ledger integrity",
    framework=ANY_FRAMEWORK,
    jurisdiction=INTERNATIONAL,
    authority="Milaan (double-entry bookkeeping)",
    status=ACTIVE,
    description="The checks that the books agree with themselves. They hold under any accounting framework, "
                "so they are listed here rather than under a standard.",
    items=(
        item("debits-equal-credits", "Debits equal credits", "Total debits equal total credits across the trial balance.",
             coverage=FULL, checks=[("reconciliation", "trial_balance_balanced")]),
        item("accounting-equation", "Assets equal liabilities plus equity",
             "The balance sheet balances: assets equal liabilities plus equity.",
             coverage=FULL, checks=[("reconciliation", "balance_sheet_balanced")]),
        item("subledger-agrees", "Fixed-asset schedule agrees with the ledger",
             "The accumulated depreciation in the fixed-asset schedule matches the ledger.",
             coverage=FULL, checks=[("reconciliation", "fixed_asset_accumulated_depreciation")]),
        item("depreciation-posted", "Depreciation is posted for the period",
             "The depreciation the schedule calls for has been posted to the ledger for the period.",
             coverage=FULL, checks=[("reconciliation", "depreciation_posted_for_period")]),
        item("source-data-complete", "Imported data reaches the ledger",
             "Imported source rows that are valid are in the ledger, and rows with errors are surfaced rather than dropped.",
             coverage=FULL, checks=[("reconciliation", "source_rows_in_ledger"), ("reconciliation", "source_rows_with_errors")]),
        item("open-items-reviewed", "Open adjustments and exceptions are reviewed",
             "Adjustments waiting for review and exceptions still open are listed before the period is signed off.",
             coverage=PARTIAL, checks=[("reconciliation", "adjustments_pending_review"), ("reconciliation", "exceptions_open_for_review")],
             note="The checks list what is still open. They do not decide whether each item was handled correctly; that is the reviewer's call."),
    ),
))