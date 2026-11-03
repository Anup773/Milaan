"""
Phase 22 -- the company accounting policy (ARCHITECTURE.md §13): pure logic, no database.

One place says what a policy contains, which values are legal, what the defaults are, who may set or change
it, and which part of Milaan actually reads each setting today. The database table (migration 0012) only
guards the shape of the data; every rule about *meaning* lives here, so adding a country, a currency or a
framework never needs a migration.

Honesty rule: FIELD_USE says, per setting, what reads it. A setting nothing reads yet says so ("Recorded for
the company; no schedule reads it yet") and the screen shows that text, so a setting never looks like it is
doing something it is not.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Dict, FrozenSet, List, Mapping, Optional, Tuple

from ..rules import registry as rules_registry
from . import countries

ROLES: Tuple[str, ...] = ("accountant", "senior_accountant", "ca", "reviewer", "admin")

# Who may set a company's policy up for the first time (it is set when a company is onboarded, and the people
# who may create companies may do that), and who may change it afterwards (it changes the numbers, so a CA or admin).
SETUP_ROLES: FrozenSet[str] = frozenset({"senior_accountant", "ca", "admin"})
CHANGE_ROLES: FrozenSet[str] = frozenset({"ca", "admin"})

CENTS = Decimal("0.01")
MAX_AMOUNT = Decimal("999999999999999.99")  # numeric(18,2)
MAX_REASON = 500

# ── legal values ─────────────────────────────────────────────────────────
LOCAL_GAAP = "Local GAAP"

COUNTRIES: Dict[str, str] = {code: p.name for code, p in countries.PROFILES.items()}
CURRENCIES: Dict[str, str] = {
    "INR": "Indian rupee", "NPR": "Nepalese rupee", "GBP": "Pound sterling", "AED": "UAE dirham", "USD": "US dollar",
    "EUR": "Euro", "SGD": "Singapore dollar", "AUD": "Australian dollar", "BDT": "Bangladeshi taka",
    "LKR": "Sri Lankan rupee", "PKR": "Pakistani rupee",
}
TAX_REGIMES: Dict[str, str] = {
    "GST": "Goods and Services Tax (GST)", "VAT": "Value added tax (VAT)", "SALES_TAX": "Sales and use tax (United States)",
    "NONE": "No indirect tax", "OTHER": "Another regime",
}
CALENDARS: Dict[str, str] = {"AD": "Gregorian (AD)", "BS": "Bikram Sambat (BS), Nepal"}
DATE_ORDERS: Dict[str, str] = {
    "DMY": "Day first: 31/03/2026 (Nepal, India, most countries)", "MDY": "Month first: 03/31/2026 (United States)",
}
NUMBER_GROUPINGS: Dict[str, str] = {"INDIAN": "12,34,567.00 (lakh and crore)", "WESTERN": "1,234,567.00"}
ROUNDINGS: Dict[str, str] = {
    "EXACT": "Exact amounts (paisa / cents)", "WHOLE": "Whole units: statements may differ from the ledger by up to 1",
}
DEPRECIATION_METHODS: Dict[str, str] = {"STRAIGHT_LINE": "Straight line"}  # written-down value is not built yet (schedules/fixed_assets.py)
DEPRECIATION_STARTS: Dict[str, str] = {
    "ACQUISITION_MONTH": "From the month the asset is acquired (the whole month counts)",
    "NEXT_MONTH": "From the month after it is acquired",
}
INVENTORY_METHODS: Dict[str, str] = {
    "FIFO": "First in, first out (FIFO)", "LIFO": "Last in, first out (LIFO), United States only",
    "WEIGHTED_AVERAGE": "Weighted average cost", "SPECIFIC_IDENTIFICATION": "Specific identification",
}
MONTHS: Tuple[str, ...] = ("January", "February", "March", "April", "May", "June", "July", "August", "September",
                           "October", "November", "December")


def framework_options() -> List[str]:
    """The accounting frameworks a company may choose: the ones in the rules catalog, plus plain local GAAP."""
    names = {rs.framework for rs in rules_registry.RULE_SETS.values()
             if rs.family == "accounting" and rs.framework != rules_registry.ANY_FRAMEWORK}
    return sorted(names, key=str.lower) + [LOCAL_GAAP]


# ── the fields ───────────────────────────────────────────────────────────
# Every field a policy has, in the order the screen shows them. `default_useful_life_months` may be absent/None.
FIELDS: Tuple[str, ...] = (
    "accounting_framework", "jurisdiction", "currency", "calendar", "date_order", "number_grouping",
    "fiscal_year_start_month", "tax_regime",
    "depreciation_method", "depreciation_start", "default_useful_life_months", "capitalization_threshold",
    "inventory_valuation_method", "statement_rounding", "review_min_amount", "review_large_amount",
)
OPTIONAL_FIELDS: FrozenSet[str] = frozenset({"default_useful_life_months"})
MONEY_FIELDS: FrozenSet[str] = frozenset({"capitalization_threshold", "review_min_amount", "review_large_amount"})
# Changing these after depreciation has been posted would make the posted figures disagree with the policy.
DEPRECIATION_LOCKED_FIELDS: Tuple[str, ...] = ("depreciation_method", "depreciation_start")
LOCKED_NAMES: Dict[str, str] = {"depreciation_method": "depreciation method", "depreciation_start": "rule for when depreciation starts"}

# What the engine uses for a company that has not set its policy up. These are the behaviours Milaan had before
# policies existed, so a company with no policy sees no change. (tests/test_policy.py keeps the review
# thresholds equal to the exception detectors' own defaults.)
DEFAULTS: Dict[str, Any] = {
    "depreciation_method": "STRAIGHT_LINE",
    "depreciation_start": "ACQUISITION_MONTH",
    "default_useful_life_months": None,
    "capitalization_threshold": Decimal("0.00"),
    "inventory_valuation_method": "WEIGHTED_AVERAGE",
    "calendar": "AD",
    "date_order": "DMY",
    "number_grouping": "INDIAN",
    "statement_rounding": "EXACT",
    "review_min_amount": Decimal("1000.00"),
    "review_large_amount": Decimal("100000.00"),
}

# Which part of Milaan reads each setting today.
FIELD_USE: Dict[str, str] = {
    "accounting_framework": "Decides which accounting rule sets are listed for this company (see Rules). Nothing checks against them yet.",
    "jurisdiction": "Decides which country-specific rule sets are listed (see Rules), which tax depreciation scheme the company has, "
                    "and the titles of its statements.",
    "currency": "Recorded for the company; no schedule reads it yet.",
    "calendar": "Read when dates are imported (ledger files, bank statements, registers) and when dates are shown. BS is for Nepal only.",
    "date_order": "Read when a date is written with the year last (01/04/2026): day first or month first. Never guessed.",
    "number_grouping": "How amounts are shown on screen: 12,34,567.00 or 1,234,567.00.",
    "fiscal_year_start_month": "Read when a fiscal year's periods are created and by the tax depreciation schedule. A month of the company's "
                               "calendar (for BS, 4 is Shrawan).",
    "tax_regime": "Decides whether tax rule sets are listed for this company (see Rules). Nothing checks against them yet.",
    "depreciation_method": "Read by the fixed-asset schedule, the depreciation posting and the reconciliation check.",
    "depreciation_start": "Read by the fixed-asset schedule, the depreciation posting and the reconciliation check.",
    "default_useful_life_months": "Used when a fixed asset is added without a useful life.",
    "capitalization_threshold": "Read when a fixed asset is added: an asset costing less is refused, to be expensed instead.",
    "inventory_valuation_method": "Recorded for the company; there is no inventory schedule yet.",
    "statement_rounding": "Read by the statements shown in whole units and by the checks between statements (a difference of up to 1 unit is allowed).",
    "review_min_amount": "Read by transaction review (exception detection): smaller entries are not flagged.",
    "review_large_amount": "Read by transaction review (exception detection): flags on entries this large are raised one priority level.",
}

FIELD_LABELS: Dict[str, str] = {
    "accounting_framework": "Accounting framework", "jurisdiction": "Country", "currency": "Currency",
    "calendar": "Calendar", "date_order": "Date order", "number_grouping": "Number format",
    "fiscal_year_start_month": "Fiscal year starts in", "tax_regime": "Tax regime",
    "depreciation_method": "Depreciation method", "depreciation_start": "Depreciation starts",
    "default_useful_life_months": "Default useful life (months)", "capitalization_threshold": "Capitalisation threshold",
    "inventory_valuation_method": "Inventory valuation method", "statement_rounding": "Statement amounts",
    "review_min_amount": "Review: smallest entry to flag",
    "review_large_amount": "Review: large entry from",
}


def options() -> Dict[str, Any]:
    """Everything the screen needs to build its drop-downs."""
    def pairs(d: Mapping[str, str]) -> List[Dict[str, str]]:
        return [{"value": k, "label": v} for k, v in d.items()]
    return {
        "accounting_frameworks": framework_options(),
        "countries": pairs(COUNTRIES),
        "currencies": [{"value": k, "label": f"{k} - {v}"} for k, v in CURRENCIES.items()],
        "months": [{"value": i + 1, "label": name} for i, name in enumerate(MONTHS)],
        "tax_regimes": pairs(TAX_REGIMES),
        "depreciation_methods": pairs(DEPRECIATION_METHODS),
        "depreciation_starts": pairs(DEPRECIATION_STARTS),
        "inventory_methods": pairs(INVENTORY_METHODS),
        "calendars": pairs(CALENDARS),
        "date_orders": pairs(DATE_ORDERS),
        "number_groupings": pairs(NUMBER_GROUPINGS),
        "roundings": pairs(ROUNDINGS),
        "country_profiles": countries.profiles_json(),
        # The screen hides choices the engine would refuse: another country's framework, LIFO outside the United States.
        "framework_countries": dict(countries.FRAMEWORK_COUNTRY),
        "lifo_frameworks": list(countries.LIFO_FRAMEWORKS),
    }


# ── who may ──────────────────────────────────────────────────────────────
def check_may_write(role: str, exists: bool) -> None:
    """PermissionError (HTTP 403) when this role may not set up (exists=False) or change (exists=True) the policy."""
    if role not in ROLES:
        raise ValueError(f"role must be one of {', '.join(ROLES)}")
    allowed = CHANGE_ROLES if exists else SETUP_ROLES
    if role not in allowed:
        what = "change the accounting policy" if exists else "set up the accounting policy"
        raise PermissionError(f"your role ({role}) cannot {what}; allowed roles: {', '.join(sorted(allowed))}")


def can_write(role: str, exists: bool) -> bool:
    try:
        check_may_write(role, exists)
    except (PermissionError, ValueError):
        return False
    return True


# ── checking a policy ────────────────────────────────────────────────────
def _pick(value: Any, allowed: Mapping[str, str], label: str) -> str:
    if not isinstance(value, str) or value.strip().upper() not in allowed:
        raise ValueError(f"{label} must be one of: {', '.join(allowed)}")
    return value.strip().upper()


def _money(value: Any, label: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, str, Decimal)):
        raise ValueError(f"{label} must be an amount like 1000 or 1000.50")
    try:
        d = Decimal(str(value).strip())
    except InvalidOperation:
        raise ValueError(f"{label} must be an amount like 1000 or 1000.50") from None
    if not d.is_finite():
        raise ValueError(f"{label} must be an amount like 1000 or 1000.50")
    if d != d.quantize(CENTS, rounding=ROUND_HALF_UP):
        raise ValueError(f"{label} can have at most two decimal places")
    d = d.quantize(CENTS, rounding=ROUND_HALF_UP)
    if d < 0:
        raise ValueError(f"{label} cannot be negative")
    if d > MAX_AMOUNT:
        raise ValueError(f"{label} is too large")
    return d


def _whole(value: Any, label: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, Decimal) and value == value.to_integral_value():
            value = int(value)
        else:
            raise ValueError(f"{label} must be a whole number from {low} to {high}")
    if not low <= value <= high:
        raise ValueError(f"{label} must be a whole number from {low} to {high}")
    return value


def validate(data: Mapping[str, Any]) -> Dict[str, Any]:
    """
    A full policy, checked and tidied: every field present (default_useful_life_months may be left out or null),
    nothing unknown, every value legal. Returns the clean values (money as Decimal with two places). Raises
    ValueError saying what to fix -- never silently corrects a value.
    """
    if not isinstance(data, Mapping):
        raise ValueError("the policy must be an object")
    unknown = sorted(set(data) - set(FIELDS))
    if unknown:
        raise ValueError(f"unknown setting(s): {', '.join(unknown)}")
    missing = [f for f in FIELDS if f not in OPTIONAL_FIELDS and data.get(f) in (None, "")]
    if missing:
        raise ValueError(f"these settings are required: {', '.join(FIELD_LABELS[f] for f in missing)}")

    framework = data["accounting_framework"]
    options_ci = {name.lower(): name for name in framework_options()}
    if not isinstance(framework, str) or framework.strip().lower() not in options_ci:
        raise ValueError(f"accounting_framework must be one of: {', '.join(framework_options())}")

    life = data.get("default_useful_life_months")
    clean: Dict[str, Any] = {
        "accounting_framework": options_ci[framework.strip().lower()],
        "jurisdiction": _pick(data["jurisdiction"], COUNTRIES, "jurisdiction"),
        "currency": _pick(data["currency"], CURRENCIES, "currency"),
        "calendar": _pick(data["calendar"], CALENDARS, "calendar"),
        "date_order": _pick(data["date_order"], DATE_ORDERS, "date_order"),
        "number_grouping": _pick(data["number_grouping"], NUMBER_GROUPINGS, "number_grouping"),
        "fiscal_year_start_month": _whole(data["fiscal_year_start_month"], "fiscal_year_start_month", 1, 12),
        "tax_regime": _pick(data["tax_regime"], TAX_REGIMES, "tax_regime"),
        "depreciation_method": _pick(data["depreciation_method"], DEPRECIATION_METHODS, "depreciation_method"),
        "depreciation_start": _pick(data["depreciation_start"], DEPRECIATION_STARTS, "depreciation_start"),
        "default_useful_life_months": None if life in (None, "") else _whole(life, "default_useful_life_months", 1, 1200),
        "capitalization_threshold": _money(data["capitalization_threshold"], "capitalization_threshold"),
        "inventory_valuation_method": _pick(data["inventory_valuation_method"], INVENTORY_METHODS, "inventory_valuation_method"),
        "statement_rounding": _pick(data["statement_rounding"], ROUNDINGS, "statement_rounding"),
        "review_min_amount": _money(data["review_min_amount"], "review_min_amount"),
        "review_large_amount": _money(data["review_large_amount"], "review_large_amount"),
    }
    if clean["review_large_amount"] < clean["review_min_amount"]:
        raise ValueError("review_large_amount cannot be smaller than review_min_amount")
    _check_country_rules(clean)
    return clean


def _check_country_rules(clean: Mapping[str, Any]) -> None:
    """Combinations that make no sense for the country chosen. Each message says what to change."""
    country = clean["jurisdiction"]
    if clean["calendar"] == "BS" and country != "NP":
        raise ValueError("the Bikram Sambat (BS) calendar is for Nepal only; choose the AD calendar for this country")
    only_in = countries.FRAMEWORK_COUNTRY.get(clean["accounting_framework"])
    if only_in is not None and only_in != country:
        raise ValueError(f"{clean['accounting_framework']} is the accounting framework of {COUNTRIES.get(only_in, only_in)} only; "
                         f"choose another framework for {COUNTRIES.get(country, country)}")
    if clean["inventory_valuation_method"] == "LIFO" and not (
            country == "US" and clean["accounting_framework"] in countries.LIFO_FRAMEWORKS):
        raise ValueError("LIFO is allowed only for a United States company under US GAAP (or local GAAP); IFRS, Ind AS, NFRS and the "
                         "UK standards forbid it")



def clean_reason(reason: Any, *, required: bool) -> Optional[str]:
    if reason is None or (isinstance(reason, str) and not reason.strip()):
        if required:
            raise ValueError("say why the policy is being changed (reason)")
        return None
    if not isinstance(reason, str):
        raise ValueError("reason must be text")
    reason = reason.strip()
    if len(reason) > MAX_REASON:
        raise ValueError(f"reason is too long (limit {MAX_REASON} characters)")
    return reason


def changed_settings(old: Optional[Mapping[str, Any]], new: Mapping[str, Any]) -> List[str]:
    """The settings whose value differs, in screen order. With no old policy, every setting counts as changed."""
    if old is None:
        return list(FIELDS)
    return [f for f in FIELDS if old.get(f) != new.get(f)]


def depreciation_locked(changed: List[str]) -> List[str]:
    return [f for f in changed if f in DEPRECIATION_LOCKED_FIELDS]


def effective_values(policy: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """The settings the engine acts on: the company's own, or the built-in defaults for a company with no policy."""
    out = dict(DEFAULTS)
    if policy:
        for f in DEFAULTS:
            out[f] = policy[f]
    return out