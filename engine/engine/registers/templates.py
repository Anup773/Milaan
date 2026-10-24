"""
What each kind of register looks like: which columns it has (under which names), and which accounts its entries use.

Adding another kind of register means adding one Template here and one builder in register.py.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple


@dataclass(frozen=True)
class Role:
    key: str
    label: str
    default: str


@dataclass(frozen=True)
class Template:
    key: str
    label: str
    description: str
    kind: str  # "invoice" | "payroll"
    fields: Dict[str, Sequence[str]]  # field -> accepted column names (lower case, letters and digits only)
    required: Tuple[str, ...]  # the date may instead come from a single date given with the import
    roles: Tuple[Role, ...]
    party_accounts_option: bool  # may each customer/supplier have its own ledger account?


_INVOICE_FIELDS: Dict[str, Sequence[str]] = {
    "date": ("invoice date", "inv date", "bill date", "document date", "doc date", "voucher date", "date"),
    "invoice": ("invoice no", "invoice number", "inv no", "inv number", "bill no", "bill number", "voucher no", "document no", "doc no", "invoice"),
    "party": ("party name", "name of party", "party", "customer name", "customer", "supplier name", "supplier", "vendor name", "vendor", "buyer", "particulars", "account name"),
    "gstin": ("gstin", "gstin uin", "gstin of supplier", "gstin of recipient", "gstin of customer", "party gstin", "customer gstin", "supplier gstin"),
    "taxable": ("taxable value", "taxable amount", "taxable", "assessable value", "basic amount", "net amount", "base amount", "amount before tax"),
    "cgst": ("cgst", "cgst amount", "central tax", "central gst"),
    "sgst": ("sgst", "sgst amount", "state tax", "state gst", "sgst utgst", "utgst", "sgst utgst amount"),
    "igst": ("igst", "igst amount", "integrated tax", "integrated gst"),
    "total": ("invoice value", "invoice amount", "total invoice value", "total amount", "grand total", "gross total", "bill amount", "total"),
}

_PAYROLL_FIELDS: Dict[str, Sequence[str]] = {
    "date": ("pay date", "payment date", "salary date", "period end", "month end", "voucher date", "date"),
    "employee": ("employee name", "name of employee", "employee", "emp name", "staff name", "name"),
    "gross": ("gross salary", "gross pay", "gross earnings", "total earnings", "gross"),
    "pf": ("pf", "epf", "provident fund", "employee pf", "pf employee", "pf deduction", "employee epf"),
    "esi": ("esi", "esic", "employee esi", "esi employee", "esi deduction"),
    "tds": ("tds", "tds on salary", "income tax", "income tax deduction"),
    "ptax": ("professional tax", "prof tax", "ptax", "pt"),
    "other": ("other deductions", "other deduction", "advance recovery", "loan recovery", "advance"),
    "total_deductions": ("total deductions", "total deduction", "deductions"),
    "net": ("net salary", "net pay", "net payable", "net amount", "take home", "net paid"),
}

TEMPLATES: Dict[str, Template] = {
    "sales": Template(
        key="sales",
        label="Sales register (with GST)",
        description="One row per sales invoice. Customer owes the invoice total; sales and each GST amount are credited. A negative row is treated as a credit note.",
        kind="invoice",
        fields=_INVOICE_FIELDS,
        required=("date", "party", "taxable"),
        roles=(
            Role("party", "Customers (control account)", "Trade Receivables"),
            Role("main", "Sales", "Sales"),
            Role("cgst", "Output CGST", "Output CGST"),
            Role("sgst", "Output SGST", "Output SGST"),
            Role("igst", "Output IGST", "Output IGST"),
            Role("round_off", "Round off", "Round Off"),
        ),
        party_accounts_option=True,
    ),
    "purchase": Template(
        key="purchase",
        label="Purchase register (with GST)",
        description="One row per purchase bill. Purchases and each GST input amount are debited; the supplier is owed the bill total. A negative row is treated as a debit note.",
        kind="invoice",
        fields=_INVOICE_FIELDS,
        required=("date", "party", "taxable"),
        roles=(
            Role("party", "Suppliers (control account)", "Trade Payables"),
            Role("main", "Purchases", "Purchases"),
            Role("cgst", "Input CGST", "Input CGST"),
            Role("sgst", "Input SGST", "Input SGST"),
            Role("igst", "Input IGST", "Input IGST"),
            Role("round_off", "Round off", "Round Off"),
        ),
        party_accounts_option=True,
    ),
    "payroll": Template(
        key="payroll",
        label="Payroll register",
        description="One row per employee. Salary expense is debited with the gross pay; each deduction and the net pay owed to the employee are credited. Gross minus deductions must equal net pay.",
        kind="payroll",
        fields=_PAYROLL_FIELDS,
        required=("date", "employee", "gross"),
        roles=(
            Role("main", "Salary expense", "Salaries and Wages"),
            Role("pf", "PF payable", "PF Payable"),
            Role("esi", "ESI payable", "ESI Payable"),
            Role("tds", "TDS on salary payable", "TDS on Salary Payable"),
            Role("ptax", "Professional tax payable", "Professional Tax Payable"),
            Role("other", "Other deductions payable", "Other Salary Deductions Payable"),
            Role("net", "Net salary payable", "Salary Payable"),
            Role("round_off", "Round off", "Round Off"),
        ),
        party_accounts_option=False,
    ),
}


def describe_all() -> List[dict]:
    """What the screen shows: every template, its columns, and the default account names."""
    out = []
    for t in TEMPLATES.values():
        out.append({
            "key": t.key,
            "label": t.label,
            "description": t.description,
            "required_columns": [f for f in t.required],
            "columns": [{"field": f, "names": list(names[:4]), "required": f in t.required} for f, names in t.fields.items()],
            "roles": [{"key": r.key, "label": r.label, "default": r.default} for r in t.roles],
            "party_accounts_option": t.party_accounts_option,
        })
    return out