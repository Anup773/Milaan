"""
Accounting frameworks Milaan knows about but does not check yet: IFRS, Ind AS, NFRS (Nepal), FRS 102 (UK).
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