"""
Auditing standards: ISA (international) and the Standards on Auditing issued in India. CATALOG_ONLY. Milaan helps
a reviewer look at transactions; it does not perform an audit or certify that one meets a standard.
"""
from __future__ import annotations

from ..registry import CATALOG_ONLY, PARTIAL, RuleSet, item, register_rule_set

_EVIDENCE_NOTE = ("The checks flag entries that appear to lack supporting evidence. They do not judge whether the evidence "
                  "is sufficient or appropriate; that is the auditor's judgement.")

register_rule_set(RuleSet(
    id="isa",
    family="auditing",
    title="International Standards on Auditing (ISA)",
    framework="ISA",
    jurisdiction="INTL",
    authority="IAASB (IFAC)",
    status=CATALOG_ONLY,
    description="Auditing standards. They govern how an audit is done, not how transactions are accounted for. "
                "Milaan does not perform an audit or certify compliance with ISA.",
    items=(
        item("isa-230", "Audit documentation", "The auditor prepares documentation that is sufficient to understand the work performed.",
             reference="ISA 230"),
        item("isa-240", "Responsibilities relating to fraud", "The auditor's responsibilities relating to fraud in an audit of financial statements.",
             reference="ISA 240"),
        item("isa-315", "Identifying and assessing the risks of material misstatement",
             "The auditor identifies and assesses the risks of material misstatement.", reference="ISA 315"),
        item("isa-500", "Audit evidence", "The auditor designs and performs procedures to obtain sufficient appropriate audit evidence.",
             reference="ISA 500", coverage=PARTIAL, checks=[("exception", "missing_evidence"), ("exception", "unsupported_expense")],
             note=_EVIDENCE_NOTE),
    ),
))

register_rule_set(RuleSet(
    id="sa-india",
    family="auditing",
    title="Standards on Auditing (India)",
    framework="SA",
    jurisdiction="IN",
    authority="Institute of Chartered Accountants of India (ICAI)",
    status=CATALOG_ONLY,
    description="The auditing standards issued by ICAI. Not checked by Milaan yet.",
    items=(
        item("sa-230", "Audit documentation", "Audit documentation.", reference="SA 230"),
        item("sa-500", "Audit evidence", "Audit evidence.", reference="SA 500", coverage=PARTIAL,
             checks=[("exception", "missing_evidence"), ("exception", "unsupported_expense")], note=_EVIDENCE_NOTE),
    ),
))