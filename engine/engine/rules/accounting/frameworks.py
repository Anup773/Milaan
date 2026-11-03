"""
Accounting frameworks Milaan knows about but does not check yet: IFRS, Ind AS and Indian AS (India), NFRS and NFRS for
SMEs (Nepal), US GAAP, FRS 102 (UK).
CATALOG_ONLY: the entries say what a framework covers, not that Milaan tests it. Where an existing check bears
on a requirement it is listed as PARTIAL with a note saying what is left untested.
"""
from __future__ import annotations

from ..registry import CATALOG_ONLY, PARTIAL, RuleSet, item, register_rule_set

_DEPRECIATION_NOTE = ("The check confirms the fixed-asset schedule agrees with the ledger. It does not test whether the "
                      "depreciation method, useful lives or capitalisation follow this standard.")

register_rule_set(RuleSet(
    id="ifrs",
    family="accounting",
    title="IFRS Accounting Standards",
    framework="IFRS",
    jurisdiction="INTL",
    authority="IFRS Foundation (IASB)",
    status=CATALOG_ONLY,
    description="International financial reporting standards (IFRS and IAS). Not checked by Milaan yet.",
    items=(
        item("ias-1", "Presentation of financial statements", "How the statements are presented: the components of a full set, "
             "going concern, comparatives and classification.", reference="IAS 1"),
        item("ias-2", "Inventories", "Inventories are measured at the lower of cost and net realisable value, with an allowed cost formula.",
             reference="IAS 2"),
        item("ias-7", "Statement of cash flows", "Cash flows are classified as operating, investing or financing.", reference="IAS 7"),
        item("ias-16", "Property, plant and equipment", "Recognition, depreciation and impairment of property, plant and equipment.",
             reference="IAS 16", coverage=PARTIAL, checks=[("reconciliation", "fixed_asset_accumulated_depreciation")],
             note=_DEPRECIATION_NOTE),
        item("ifrs-15", "Revenue from contracts with customers", "Revenue is recognised when control of goods or services passes to the customer.",
             reference="IFRS 15"),
    ),
))

register_rule_set(RuleSet(
    id="ind-as",
    family="accounting",
    title="Indian Accounting Standards (Ind AS)",
    framework="Ind AS",
    jurisdiction="IN",
    authority="Ministry of Corporate Affairs, India",
    status=CATALOG_ONLY,
    description="Accounting standards converged with IFRS and notified in India. Not checked by Milaan yet.",
    items=(
        item("ind-as-1", "Presentation of financial statements", "How the financial statements are presented.", reference="Ind AS 1"),
        item("ind-as-2", "Inventories", "Measurement of inventories.", reference="Ind AS 2"),
        item("ind-as-16", "Property, plant and equipment", "Recognition and depreciation of property, plant and equipment.",
             reference="Ind AS 16", coverage=PARTIAL, checks=[("reconciliation", "fixed_asset_accumulated_depreciation")],
             note=_DEPRECIATION_NOTE),
        item("ind-as-115", "Revenue from contracts with customers", "Recognition of revenue from contracts with customers.", reference="Ind AS 115"),
    ),
))

register_rule_set(RuleSet(
    id="nfrs",
    family="accounting",
    title="Nepal Financial Reporting Standards (NFRS)",
    framework="NFRS",
    jurisdiction="NP",
    authority="Accounting Standards Board, Nepal",
    status=CATALOG_ONLY,
    description="Financial reporting standards used in Nepal. Not checked by Milaan yet.",
    items=(
        item("nfrs-presentation", "Presentation of financial statements", "How the financial statements are presented."),
        item("nfrs-inventories", "Inventories", "Measurement of inventories."),
        item("nfrs-ppe", "Property, plant and equipment", "Recognition and depreciation of property, plant and equipment.",
             coverage=PARTIAL, checks=[("reconciliation", "fixed_asset_accumulated_depreciation")], note=_DEPRECIATION_NOTE),
        item("nfrs-revenue", "Revenue", "Recognition of revenue."),
    ),
))

register_rule_set(RuleSet(
    id="frs-102",
    family="accounting",
    title="FRS 102 (UK GAAP)",
    framework="FRS 102",
    jurisdiction="GB",
    authority="Financial Reporting Council, UK",
    status=CATALOG_ONLY,
    description="The main financial reporting standard under UK GAAP. Not checked by Milaan yet.",
    items=(
        item("frs-102-s4", "Statement of financial position", "How the statement of financial position is presented.", reference="Section 4"),
        item("frs-102-s13", "Inventories", "Measurement of inventories.", reference="Section 13"),
        item("frs-102-s17", "Property, plant and equipment", "Recognition and depreciation of property, plant and equipment.",
             reference="Section 17", coverage=PARTIAL, checks=[("reconciliation", "fixed_asset_accumulated_depreciation")],
             note=_DEPRECIATION_NOTE),
        item("frs-102-s23", "Revenue", "Recognition of revenue.", reference="Section 23"),
    ),
))

register_rule_set(RuleSet(
    id="us-gaap",
    family="accounting",
    title="US GAAP (FASB Accounting Standards Codification)",
    framework="US GAAP",
    jurisdiction="US",
    authority="Financial Accounting Standards Board (FASB), United States",
    status=CATALOG_ONLY,
    description="Generally accepted accounting principles in the United States. Not checked by Milaan yet.",
    items=(
        item("asc-210", "Balance sheet", "How the balance sheet is presented, including the current and non-current split.", reference="ASC 210"),
        item("asc-220", "Income statement", "How the income statement and comprehensive income are presented.", reference="ASC 220"),
        item("asc-230", "Statement of cash flows", "Cash flows are classified as operating, investing or financing.", reference="ASC 230"),
        item("asc-330", "Inventory", "Inventory is measured at the lower of cost and net realisable value (or market for LIFO). FIFO, LIFO and "
             "average cost are all allowed.", reference="ASC 330"),
        item("asc-360", "Property, plant and equipment", "Recognition, depreciation and impairment of property, plant and equipment.",
             reference="ASC 360", coverage=PARTIAL, checks=[("reconciliation", "fixed_asset_accumulated_depreciation")],
             note=_DEPRECIATION_NOTE),
        item("asc-606", "Revenue from contracts with customers", "Revenue is recognised when control passes to the customer.", reference="ASC 606"),
        item("asc-842", "Leases", "Lessees recognise a right-of-use asset and a lease liability.", reference="ASC 842"),
    ),
))

register_rule_set(RuleSet(
    id="indian-as",
    family="accounting",
    title="Accounting Standards (India, non-Ind AS companies)",
    framework="Indian AS",
    jurisdiction="IN",
    authority="Institute of Chartered Accountants of India (ICAI) and the Ministry of Corporate Affairs",
    status=CATALOG_ONLY,
    description="The Accounting Standards notified under the Companies (Accounting Standards) Rules for companies that do not follow Ind AS. "
                "Not checked by Milaan yet.",
    items=(
        item("as-1", "Disclosure of accounting policies", "The significant accounting policies are disclosed.", reference="AS 1"),
        item("as-2", "Valuation of inventories", "Inventories are valued at the lower of cost and net realisable value.", reference="AS 2"),
        item("as-3", "Cash flow statements", "Cash flows are classified as operating, investing or financing.", reference="AS 3"),
        item("as-10", "Property, plant and equipment", "Recognition and depreciation of property, plant and equipment.", reference="AS 10",
             coverage=PARTIAL, checks=[("reconciliation", "fixed_asset_accumulated_depreciation")], note=_DEPRECIATION_NOTE),
        item("as-9", "Revenue recognition", "Recognition of revenue from sales and services.", reference="AS 9"),
        item("as-22", "Accounting for taxes on income", "Current and deferred tax are recognised.", reference="AS 22"),
    ),
))

register_rule_set(RuleSet(
    id="nfrs-smes",
    family="accounting",
    title="Nepal Financial Reporting Standards for SMEs (NFRS for SMEs)",
    framework="NFRS for SMEs",
    jurisdiction="NP",
    authority="Accounting Standards Board, Nepal",
    status=CATALOG_ONLY,
    description="The Nepali standard for small and medium-sized entities, based on the IFRS for SMEs. Not checked by Milaan yet.",
    items=(
        item("nfrs-smes-sfp", "Statement of financial position", "How the statement of financial position is presented.",
             reference="IFRS for SMEs section 4"),
        item("nfrs-smes-inv", "Inventories", "Measurement of inventories.", reference="IFRS for SMEs section 13"),
        item("nfrs-smes-ppe", "Property, plant and equipment", "Recognition and depreciation of property, plant and equipment.",
             reference="IFRS for SMEs section 17", coverage=PARTIAL,
             checks=[("reconciliation", "fixed_asset_accumulated_depreciation")], note=_DEPRECIATION_NOTE),
        item("nfrs-smes-rev", "Revenue", "Recognition of revenue.", reference="IFRS for SMEs section 23"),
    ),
))