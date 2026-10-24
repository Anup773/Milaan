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
