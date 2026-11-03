"""
Tax regimes Milaan knows about but does not check yet. Rates, thresholds and filing rules change and differ by
state and case, so nothing numeric is recorded here. CATALOG_ONLY: confirm every position against current law.
"""
from __future__ import annotations

from ..registry import CATALOG_ONLY, RuleSet, item, register_rule_set

register_rule_set(RuleSet(
    id="india-gst",
    family="tax",
    title="Goods and Services Tax (India)",
    framework="GST",
    jurisdiction="IN",
    authority="GST Council and the Central and State governments, India",
    status=CATALOG_ONLY,
    description="Indirect tax on supplies of goods and services in India. Milaan can read GST registers in (see GST & payroll) "
                "but does not check them against the law yet.",
    items=(
        item("gst-invoice", "Tax invoice contents", "A tax invoice carries the details the law requires."),
        item("gst-itc", "Input tax credit", "Input tax credit claimed agrees with the supplier's filed data."),
        item("gst-returns", "Return filing", "Outward and net tax liability returns are filed and agree with the books."),
    ),
))

register_rule_set(RuleSet(
    id="india-tds",
    family="tax",
    title="Tax deducted at source (India)",
    framework="Income tax",
    jurisdiction="IN",
    authority="Income Tax Department, India",
    status=CATALOG_ONLY,
    description="Income tax withheld from payments such as salary and contractor fees. Not checked by Milaan yet.",
    items=(
        item("tds-deduction", "Deduction on covered payments", "Tax is deducted from payments that the law covers."),
        item("tds-deposit", "Deposit and return", "Tax deducted is deposited and reported on time."),
    ),
))

register_rule_set(RuleSet(
    id="nepal-vat",
    family="tax",
    title="Value added tax (Nepal)",
    framework="VAT",
    jurisdiction="NP",
    authority="Inland Revenue Department, Nepal",
    status=CATALOG_ONLY,
    description="Value added tax on goods and services in Nepal. Not checked by Milaan yet.",
    items=(
        item("np-vat-invoice", "VAT invoice contents", "A VAT invoice carries the details the law requires."),
        item("np-vat-return", "VAT return", "Output and input VAT agree with the books and the return is filed."),
    ),
))

register_rule_set(RuleSet(
    id="uk-vat",
    family="tax",
    title="Value added tax (United Kingdom)",
    framework="VAT",
    jurisdiction="GB",
    authority="HM Revenue & Customs, UK",
    status=CATALOG_ONLY,
    description="Value added tax in the United Kingdom. Not checked by Milaan yet.",
    items=(
        item("uk-vat-invoice", "VAT invoice contents", "A VAT invoice carries the details the law requires."),
        item("uk-vat-return", "VAT return", "Output and input VAT agree with the books and the return is filed."),
    ),
))

register_rule_set(RuleSet(
    id="uae-vat",
    family="tax",
    title="Value added tax (United Arab Emirates)",
    framework="VAT",
    jurisdiction="AE",
    authority="Federal Tax Authority, UAE",
    status=CATALOG_ONLY,
    description="Value added tax in the United Arab Emirates. Not checked by Milaan yet.",
    items=(
        item("ae-vat-invoice", "Tax invoice contents", "A tax invoice carries the details the law requires."),
        item("ae-vat-return", "VAT return", "Output and input VAT agree with the books and the return is filed."),
    ),
))

register_rule_set(RuleSet(
    id="nepal-income-tax",
    family="tax",
    title="Income tax and tax depreciation (Nepal)",
    framework="Income tax",
    jurisdiction="NP",
    authority="Inland Revenue Department, Nepal (Income Tax Act, 2058)",
    status=CATALOG_ONLY,
    description="Income tax in Nepal, including the depreciation pools of Schedule 2. Milaan calculates the tax depreciation schedule "
                "(Schedules > Tax depreciation) but does not check filed returns against the law.",
    items=(
        item("np-tax-depreciation", "Depreciation deduction (Schedule 2)", "Depreciation is deducted by pool (A to E) at the scheduled rates, with "
             "additions taken in thirds by the time of year they were bought."),
        item("np-tax-holiday", "Tax holiday and exemptions", "Income that is exempt or taxed at a reduced rate is separated from taxable income."),
        item("np-tax-advance", "Advance tax instalments", "Advance tax is paid on time; interest and fees apply when it is not."),
    ),
))

register_rule_set(RuleSet(
    id="india-income-tax-depreciation",
    family="tax",
    title="Income tax depreciation (India)",
    framework="Income tax",
    jurisdiction="IN",
    authority="Income Tax Department, India",
    status=CATALOG_ONLY,
    description="Depreciation on blocks of assets at written-down value. Milaan calculates the tax depreciation schedule "
                "(Schedules > Tax depreciation) but does not check filed returns against the law.",
    items=(
        item("in-tax-block-depreciation", "Block depreciation", "Depreciation is allowed on each block of assets at the prescribed rate, "
             "at half rate for additions used under 180 days."),
        item("in-tax-block-disposal", "Sale of assets in a block", "Sale proceeds reduce the block; a negative block is a short-term capital gain."),
    ),
))

register_rule_set(RuleSet(
    id="us-macrs",
    family="tax",
    title="MACRS tax depreciation (United States, federal)",
    framework="Income tax",
    jurisdiction="US",
    authority="Internal Revenue Service, United States",
    status=CATALOG_ONLY,
    description="The Modified Accelerated Cost Recovery System. Milaan calculates the MACRS schedule (Schedules > Tax depreciation) but "
                "does not check filed returns, and does not model state rules that differ from federal.",
    items=(
        item("us-macrs-tables", "Recovery periods and conventions", "Property is depreciated over its recovery period under the half-year, "
             "mid-quarter or mid-month convention."),
        item("us-macrs-179-bonus", "Section 179 and bonus depreciation", "Elected Section 179 expense and bonus depreciation reduce the basis."),
    ),
))

register_rule_set(RuleSet(
    id="us-sales-tax",
    family="tax",
    title="Sales and use tax (United States)",
    framework="SALES_TAX",
    jurisdiction="US",
    authority="State and local tax authorities, United States",
    status=CATALOG_ONLY,
    description="Sales and use tax is set state by state. Not checked by Milaan.",
    items=(
        item("us-sales-tax-collect", "Collection and returns", "Tax is collected where the company has nexus and returns are filed to each state."),
    ),
))