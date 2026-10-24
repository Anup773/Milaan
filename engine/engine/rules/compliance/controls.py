"""
Internal controls Milaan enforces as product features, and regulatory areas it only lists. ISO/IEC 27001 is here
as a boundary marker, not a claim: it concerns securing information systems (not accounting or auditing), and
certification is a separate assessment that building security features does not provide.
"""
from __future__ import annotations

from ..registry import ACTIVE, ANY_FRAMEWORK, CATALOG_ONLY, FULL, INTERNATIONAL, PARTIAL, RuleSet, item, register_rule_set

register_rule_set(RuleSet(
    id="internal-controls",
    family="compliance",
    title="Internal controls in Milaan",
    framework=ANY_FRAMEWORK,
    jurisdiction=INTERNATIONAL,
    authority="Milaan (product controls)",
    status=ACTIVE,
    description="Controls built into how Milaan works, so that a change is approved, a closed period stays closed and "
                "every change can be traced.",
    items=(
        item("maker-checker", "Changes need approval", "A change reaches the books only after the required approvals.",
             coverage=FULL, checks=[("feature", "approval_workflow")]),
        item("period-lock", "Closed periods stay locked", "A finalised period is locked, and reopening it needs approval.",
             coverage=FULL, checks=[("feature", "period_locking")]),
        item("traceability", "Every change is recorded", "Who did what and when is kept in an append-only log.",
             coverage=FULL, checks=[("feature", "audit_trail")]),
        item("transaction-review", "Unusual transactions are flagged for review",
             "Possible duplicates, vendor mismatches, unusual amounts and cut-off problems are flagged for a person to review.",
             coverage=PARTIAL,
             checks=[("exception", "duplicate_invoice"), ("exception", "duplicate_amount"), ("exception", "vendor_mismatch"),
                     ("exception", "unusual_transaction"), ("exception", "period_cutoff")],
             note="Flags are prompts for a reviewer, never findings. They do not cover every kind of error or irregularity."),
    ),
))

register_rule_set(RuleSet(
    id="record-keeping",
    family="compliance",
    title="Record keeping",
    framework=ANY_FRAMEWORK,
    jurisdiction=INTERNATIONAL,
    authority="Varies by jurisdiction",
    status=CATALOG_ONLY,
    description="Books and supporting records must be kept, and be producible, for the period the local law requires. "
                "The period differs by country, so none is recorded here. Not checked by Milaan yet.",
    items=(
        item("retention-period", "Retention period", "Records are kept for at least the period the local law requires."),
        item("record-availability", "Records can be produced", "Books and supporting documents can be produced on request."),
    ),
))

register_rule_set(RuleSet(
    id="information-security",
    family="compliance",
    title="Information security management (ISO/IEC 27001 and 27002)",
    framework=ANY_FRAMEWORK,
    jurisdiction=INTERNATIONAL,
    authority="ISO and IEC",
    status=CATALOG_ONLY,
    description="Standards for managing the security of information systems. They are not accounting or auditing rules. "
                "Milaan is not certified against them, and adding security features does not make it so: certification "
                "is a separate assessment by an accredited body.",
    items=(
        item("isms", "Information security management system", "An organisation-wide management system for information security, "
             "assessed by an accredited certification body.", reference="ISO/IEC 27001"),
        item("security-controls", "Security controls", "A reference set of information security controls.", reference="ISO/IEC 27002"),
    ),
))