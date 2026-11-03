"""
Country profiles (Phase 24) -- what "I am a company in Nepal / India / the United States" sets up. Pure data, no
database; adding a country is adding one profile here.

A profile does two things. It SUGGESTS the policy values that country's accountants normally use (the policy
screen fills them in and the user can change them), and it names the country's tax-depreciation scheme and the
titles of the statements. It does not change how the rest of Milaan works: ledgers, imports, adjustments,
approvals, the audit trail and the checks are the same everywhere.

Honesty rule: every profile carries a `guide` that says, topic by topic, what Milaan does for that country
today ("built"), partly does ("partial") and does not do yet ("not_built"). The screen shows it, so choosing a
country never looks like it switches on rules that are not there.

support: "full"  -- Nepal, India and the United States: calendar, dates, tax depreciation and statement titles.
         "basic" -- other countries: sensible defaults only (currency, date order, number format, framework).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

BUILT, PARTIAL, NOT_BUILT = "built", "partial", "not_built"

# The tax-depreciation schemes the engine has (engine/schedules/tax_dep/).
NP_SCHEDULE_2 = "NP_SCHEDULE_2"
IN_BLOCKS = "IN_BLOCKS"
US_MACRS = "US_MACRS"

STATEMENTS_IFRS = {
    "balance_sheet": "Statement of Financial Position", "profit_and_loss": "Statement of Profit or Loss",
    "cash_flow": "Statement of Cash Flows", "changes_in_equity": "Statement of Changes in Equity",
    "trial_balance": "Trial Balance", "profit_label": "Profit for the year", "equity_label": "Equity",
}


def _g(topic: str, status: str, text: str) -> Dict[str, str]:
    return {"topic": topic, "status": status, "text": text}


@dataclass(frozen=True)
class CountryProfile:
    code: str
    name: str
    support: str                       # "full" | "basic"
    currency: str
    calendar: str                      # the calendar the books are kept in; the first of calendar_choices
    calendar_choices: Tuple[str, ...]
    date_order: str                    # DMY | MDY, for dates written with the year last
    number_grouping: str               # INDIAN (12,34,567.00) | WESTERN (1,234,567.00)
    fiscal_year_start_month: int       # a month of `calendar` (for BS, 4 is Shrawan)
    frameworks: Tuple[str, ...]        # the accounting frameworks usually used here; the first is the suggestion
    tax_regime: str                    # the suggestion
    tax_regime_choices: Tuple[str, ...]
    inventory_methods: Tuple[str, ...]
    statement_rounding: str            # the suggestion: EXACT or WHOLE
    statements: Dict[str, str] = field(default_factory=dict)
    tax_depreciation_scheme: Optional[str] = None
    guide: Tuple[Dict[str, str], ...] = ()
    fiscal_year_note: str = ""

    @property
    def default_framework(self) -> str:
        return self.frameworks[0]

    def suggested_policy(self) -> Dict[str, Any]:
        """The policy values this country suggests (the fields a country can decide; thresholds and so on are left alone)."""
        return {
            "accounting_framework": self.default_framework, "jurisdiction": self.code, "currency": self.currency,
            "calendar": self.calendar, "date_order": self.date_order, "number_grouping": self.number_grouping,
            "fiscal_year_start_month": self.fiscal_year_start_month, "tax_regime": self.tax_regime,
            "inventory_valuation_method": self.inventory_methods[0], "statement_rounding": self.statement_rounding,
        }

    def to_json(self) -> Dict[str, Any]:
        return {
            "code": self.code, "name": self.name, "support": self.support, "currency": self.currency,
            "calendar": self.calendar, "calendar_choices": list(self.calendar_choices), "date_order": self.date_order,
            "number_grouping": self.number_grouping, "fiscal_year_start_month": self.fiscal_year_start_month,
            "frameworks": list(self.frameworks), "tax_regime": self.tax_regime,
            "tax_regime_choices": list(self.tax_regime_choices), "inventory_methods": list(self.inventory_methods),
            "statement_rounding": self.statement_rounding, "statements": dict(self.statements),
            "tax_depreciation_scheme": self.tax_depreciation_scheme, "fiscal_year_note": self.fiscal_year_note,
            "guide": [dict(g) for g in self.guide], "suggested": self.suggested_policy(),
        }


NEPAL = CountryProfile(
    code="NP", name="Nepal", support="full", currency="NPR", calendar="BS", calendar_choices=("BS", "AD"),
    date_order="DMY", number_grouping="INDIAN", fiscal_year_start_month=4,
    frameworks=("NFRS", "NFRS for SMEs", "Local GAAP"), tax_regime="VAT", tax_regime_choices=("VAT", "NONE", "OTHER"),
    inventory_methods=("WEIGHTED_AVERAGE", "FIFO", "SPECIFIC_IDENTIFICATION"), statement_rounding="WHOLE",
    statements=dict(STATEMENTS_IFRS, profit_and_loss="Statement of Profit or Loss and Other Comprehensive Income"),
    tax_depreciation_scheme=NP_SCHEDULE_2,
    fiscal_year_note="The fiscal year runs from Shrawan 1 to the end of Ashadh (about 16 July to 16 July). The calendar is Bikram Sambat (BS).",
    guide=(
        _g("Dates and fiscal year", BUILT, "Dates are read and shown in Bikram Sambat (for example 2082-04-01, 01/04/2082 or 1-Shrawan-2082, "
           "also in Devanagari digits) and stored as AD. The fiscal year is Shrawan 1 to the end of Ashadh. BS years after 2083 are "
           "provisional in Milaan's calendar table and are flagged whenever they are used. A date such as 05/04/2082 is read day first "
           "because that is the company's setting: if a file is month first, change the setting rather than trusting the dates. "
           "A fiscal year's twelve BS-month periods can be created for you."),
        _g("Tax depreciation (Income Tax Act 2058, Schedule 2)", BUILT, "Pools A to D on the declining balance with the one-third / two-thirds "
           "timing of additions, pool E straight-line, disposals and the Rs 2,000 small-balance rule. Rates are data you can change per "
           "company and per date (a powerhouse project adds one third to the rates; Upper Syange's statements use that). Confirm with your "
           "CA how pool E's first year is treated and whether pool A also gets the powerhouse uplift: the sources read are not clear."),
        _g("Statements", PARTIAL, "Statement of financial position, profit or loss, changes in equity and a single net cash movement. "
           "The cash flow is not yet split into operating, investing and financing, and there are no notes or group/company columns. "
           "The statements can be checked against each other, and against the figures printed in a signed statement (within one rupee "
           "when the statements are in whole rupees)."),
        _g("Income tax computation (tax holiday, advance tax interest)", NOT_BUILT, "Not built: the hydropower tax holiday split, "
           "advance-tax instalments and the section 117/118/119 fees and interest."),
        _g("Deferred tax", NOT_BUILT, "Not built."),
        _g("VAT, TDS, SSF, provident fund, gratuity", NOT_BUILT, "Not built. Registers can be read in; nothing is checked against the law."),
        _g("Leases (NFRS 16), consolidation, earnings per share", NOT_BUILT, "Not built."),
        _g("Nepali-language statements", NOT_BUILT, "Not built: output is in English with Western digits."),
    ),
)

INDIA = CountryProfile(
    code="IN", name="India", support="full", currency="INR", calendar="AD", calendar_choices=("AD",),
    date_order="DMY", number_grouping="INDIAN", fiscal_year_start_month=4,
    frameworks=("Indian AS", "Ind AS", "Local GAAP"), tax_regime="GST", tax_regime_choices=("GST", "NONE", "OTHER"),
    inventory_methods=("WEIGHTED_AVERAGE", "FIFO", "SPECIFIC_IDENTIFICATION"), statement_rounding="WHOLE",
    statements=dict(STATEMENTS_IFRS, balance_sheet="Balance Sheet", profit_and_loss="Statement of Profit and Loss",
                    cash_flow="Cash Flow Statement"),
    tax_depreciation_scheme=IN_BLOCKS,
    fiscal_year_note="The fiscal (financial) year runs 1 April to 31 March.",
    guide=(
        _g("Dates and fiscal year", BUILT, "Day-first dates (01/04/2026); fiscal year 1 April to 31 March, labelled like 2025-26. "
           "A BS-looking year such as 2082 is refused instead of being read as an AD year. A date such as 05/04/2026 is read day first, "
           "because that is the company's setting. The fiscal year's twelve monthly periods can be created for you."),
        _g("Tax depreciation (block of assets, written-down value)", BUILT, "Blocks on the written-down value, the half-rate rule for "
           "additions used under 180 days, sale proceeds reducing the block and the short-term capital gain when a block goes "
           "negative. Rates are data you can change per company and per date. Main blocks only: check against the rates table. "
           "For tax years from 2026-27 the Income-tax Act, 2025 applies (the rates carry over, according to the sources read, "
           "but confirm)."),
        _g("Statements", PARTIAL, "Balance sheet, statement of profit and loss, changes in equity and a single net cash movement, with "
           "Schedule III titles. The Schedule III line-by-line format and notes are not built."),
        _g("Book depreciation (Companies Act Schedule II lives)", NOT_BUILT, "Book depreciation is straight-line from the useful life you "
           "enter. Schedule II's table of lives and the written-down-value book method are not built."),
        _g("GST, TDS, payroll", PARTIAL, "GST and payroll registers can be read in (GST & payroll). Nothing is checked against the law."),
        _g("Ind AS specifics (leases, deferred tax, consolidation)", NOT_BUILT, "Not built."),
    ),
)

UNITED_STATES = CountryProfile(
    code="US", name="United States", support="full", currency="USD", calendar="AD", calendar_choices=("AD",),
    date_order="MDY", number_grouping="WESTERN", fiscal_year_start_month=1,
    frameworks=("US GAAP", "IFRS", "Local GAAP"), tax_regime="SALES_TAX", tax_regime_choices=("SALES_TAX", "NONE", "OTHER"),
    inventory_methods=("FIFO", "LIFO", "WEIGHTED_AVERAGE", "SPECIFIC_IDENTIFICATION"), statement_rounding="EXACT",
    statements={
        "balance_sheet": "Balance Sheet", "profit_and_loss": "Income Statement", "cash_flow": "Statement of Cash Flows",
        "changes_in_equity": "Statement of Stockholders' Equity", "trial_balance": "Trial Balance",
        "profit_label": "Net income", "equity_label": "Stockholders' equity",
    },
    tax_depreciation_scheme=US_MACRS,
    fiscal_year_note="Most companies use the calendar year; a different fiscal year can be chosen.",
    guide=(
        _g("Dates and numbers", BUILT, "Month-first dates (03/31/2026); amounts as 1,234,567.00. A day-first date that cannot be a month, "
           "such as 31/03/2026, is refused with a reason. One that could be either, such as 05/03/2026, is read month first because that "
           "is the company's setting, so check a day-first file before importing it."),
        _g("Tax depreciation (MACRS, federal)", BUILT, "General Depreciation System tables for 3, 5, 7, 10, 15 and 20-year property "
           "(half-year and mid-quarter conventions, the 40% test) and 27.5 and 39-year real property (mid-month). Bonus depreciation "
           "percentage and Section 179 amounts are entered per asset; the limits are not enforced. State depreciation rules "
           "that differ from federal are not modelled."),
        _g("Inventory", PARTIAL, "LIFO is available as a policy choice (it is allowed under US GAAP, not under IFRS). Nothing computes "
           "inventory yet."),
        _g("Statements", PARTIAL, "Balance sheet, income statement, statement of stockholders' equity and a single net cash movement. "
           "No notes, no classified current / non-current split, no operating/investing/financing cash flow."),
        _g("Sales and use tax, payroll tax, 1099, income tax returns", NOT_BUILT, "Not built. US sales tax is set state by state."),
        _g("ASC 606 revenue, ASC 842 leases, consolidation", NOT_BUILT, "Not built."),
    ),
)


def _basic(code: str, name: str, currency: str, grouping: str, start_month: int, frameworks: Tuple[str, ...], tax: str,
           tax_choices: Tuple[str, ...] = ("VAT", "GST", "NONE", "OTHER")) -> CountryProfile:
    return CountryProfile(
        code=code, name=name, support="basic", currency=currency, calendar="AD", calendar_choices=("AD",), date_order="DMY",
        number_grouping=grouping, fiscal_year_start_month=start_month, frameworks=frameworks, tax_regime=tax,
        tax_regime_choices=tax_choices, inventory_methods=("WEIGHTED_AVERAGE", "FIFO", "SPECIFIC_IDENTIFICATION"),
        statement_rounding="EXACT", statements=dict(STATEMENTS_IFRS), tax_depreciation_scheme=None,
        guide=(
            _g("Country defaults", BUILT, "Currency, day-first dates, number format, a usual accounting framework and tax regime are "
               "suggested. The fiscal-year start is a common choice; change it if the company's year differs."),
            _g("Tax depreciation, statutory formats, local tax checks", NOT_BUILT, "Not built for this country yet. Everything else "
               "(imports, ledger, adjustments, approvals, audit trail, reconciliation) works the same as for any country."),
        ),
    )


PROFILES: Dict[str, CountryProfile] = {p.code: p for p in (
    NEPAL, INDIA, UNITED_STATES,
    _basic("GB", "United Kingdom", "GBP", "WESTERN", 4, ("FRS 102", "IFRS", "Local GAAP"), "VAT"),
    _basic("AE", "United Arab Emirates", "AED", "WESTERN", 1, ("IFRS", "Local GAAP"), "VAT"),
    _basic("SG", "Singapore", "SGD", "WESTERN", 1, ("IFRS", "Local GAAP"), "GST"),
    _basic("AU", "Australia", "AUD", "WESTERN", 7, ("IFRS", "Local GAAP"), "GST"),
    _basic("BD", "Bangladesh", "BDT", "INDIAN", 7, ("IFRS", "Local GAAP"), "VAT"),
    _basic("LK", "Sri Lanka", "LKR", "WESTERN", 4, ("IFRS", "Local GAAP"), "VAT"),
    _basic("PK", "Pakistan", "PKR", "INDIAN", 7, ("IFRS", "Local GAAP"), "GST"),
)}

# Frameworks that belong to one country only, so a company cannot pick another country's standard by mistake.
FRAMEWORK_COUNTRY: Dict[str, str] = {
    "Ind AS": "IN", "Indian AS": "IN", "NFRS": "NP", "NFRS for SMEs": "NP", "US GAAP": "US", "FRS 102": "GB",
}
# Inventory cost formulas: LIFO is allowed under US GAAP only (IFRS, Ind AS, NFRS and the UK standards forbid it).
LIFO_FRAMEWORKS = ("US GAAP", "Local GAAP")


def profile_for(code: Optional[str]) -> Optional[CountryProfile]:
    return PROFILES.get((code or "").upper())


def profiles_json() -> List[Dict[str, Any]]:
    """Full-support countries first, then the rest by name."""
    return [p.to_json() for p in sorted(PROFILES.values(), key=lambda p: (p.support != "full", p.name))]