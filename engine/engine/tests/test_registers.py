"""Register connector (sales, purchase, payroll): columns, vouchers, GST and payroll checks, duplicates, files, command line."""
from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from engine.mapping.planner import Period, SourceRow, plan_entries
from engine.registers import cli
from engine.registers.register import (
    LINE_ROW_OFFSET,
    RegisterError,
    detect_columns,
    keys_of,
    mark_duplicates,
    parse_file,
    parse_table,
    resolve_accounts,
)
from engine.registers.templates import TEMPLATES, describe_all

D = Decimal
SALES_HEADER = ["Invoice Date", "Invoice No", "Customer Name", "GSTIN", "Taxable Value", "CGST", "SGST", "IGST", "Invoice Value"]
PAYROLL_HEADER = ["Emp Name", "Gross Salary", "PF", "ESI", "TDS", "Professional Tax", "Total Deductions", "Net Salary"]
PERIOD = Period("P1", "FY26", date(2025, 4, 1), date(2026, 3, 31), False)


def sales(*rows, header=SALES_HEADER):
    return [["Sales Register"], ["Acme Traders"], header, *rows]


def lines(parsed):
    """(account, debit, credit) of every saved line, in order."""
    return [(r.account_ref, r.debit, r.credit) for r in parsed.result.rows]


def plan_of(parsed, mapping=None):
    rows = [SourceRow(str(i), r.row_number, r.account_ref, r.transaction_date, r.description, r.debit, r.credit, r.reference, "ERROR" if any(x.row_number == r.row_number and x.severity.value == "ERROR" for x in parsed.result.issues) else "OK")
            for i, r in enumerate(parsed.result.rows)]
    names = {r.account_ref.casefold() for r in parsed.result.rows}
    mapping = mapping or {n: n for n in names}
    return plan_entries(rows, mapping, [PERIOD])


# ---- columns ---------------------------------------------------------------------------------------------------------

def test_every_template_describes_itself_for_the_screen():
    info = {t["key"]: t for t in describe_all()}
    assert set(info) == {"sales", "purchase", "payroll"}
    assert all(t["roles"] and t["columns"] and t["description"] for t in info.values())
    assert [r["default"] for r in info["sales"]["roles"]][:2] == ["Trade Receivables", "Sales"]


def test_common_register_headings_are_recognised():
    cols = detect_columns(["Bill Date", "Bill No.", "Supplier Name", "Taxable Amount", "CGST Amount", "SGST/UTGST", "IGST Amount", "Total Invoice Value"], TEMPLATES["purchase"])
    assert set(cols) == {"date", "invoice", "party", "taxable", "cgst", "sgst", "igst", "total"}


def test_a_file_that_is_not_a_register_says_what_is_needed():
    with pytest.raises(RegisterError) as info:
        parse_table([["Name", "Age"], ["a", "1"]], "sales")
    assert "column headings" in str(info.value) and "taxable" in str(info.value)


def test_unknown_template_and_unknown_role_are_refused():
    with pytest.raises(RegisterError):
        parse_table(sales(), "inventory")
    with pytest.raises(RegisterError):
        resolve_accounts(TEMPLATES["sales"], {"nonsense": "x"})


# ---- sales -------------------------------------------------------------------------------------------------------------

def test_a_sales_invoice_becomes_a_balanced_voucher():
    p = parse_table(sales(["01/04/2025", "INV-1", "Acme Ltd", "27AAPFU0939F1ZV", "10,000.00", "900.00", "900.00", "", "11,800.00"]), "sales")
    assert lines(p) == [
        ("Trade Receivables", D("11800.00"), D("0")),
        ("Sales", D("0"), D("10000.00")),
        ("Output CGST", D("0"), D("900.00")),
        ("Output SGST", D("0"), D("900.00")),
    ]
    assert p.result.total_debit == p.result.total_credit == D("11800.00")
    assert p.result.rows[0].description == "Inv INV-1 - Acme Ltd" and p.result.rows[0].transaction_date == date(2025, 4, 1)
    assert not p.result.issues and p.stats.records == 1
    assert [r.row_number for r in p.result.rows] == [4, 4 + LINE_ROW_OFFSET, 4 + 2 * LINE_ROW_OFFSET, 4 + 3 * LINE_ROW_OFFSET]
    assert len({r.reference for r in p.result.rows}) == 1


def test_interstate_invoice_uses_igst_and_no_total_column_is_fine():
    p = parse_table(sales(["02/04/2025", "INV-2", "Beta", "", "5000", "", "", "900", ""]), "sales")
    assert ("Output IGST", D("0"), D("900")) in lines(p) and ("Trade Receivables", D("5900"), D("0")) in lines(p)


def test_credit_notes_reverse_every_side():
    p = parse_table(sales(["03/04/2025", "CN-1", "Acme", "", "-1,000.00", "-90.00", "-90.00", "", "-1,180.00"]), "sales")
    assert lines(p) == [
        ("Trade Receivables", D("0"), D("1180.00")),
        ("Sales", D("1000.00"), D("0")),
        ("Output CGST", D("90.00"), D("0")),
        ("Output SGST", D("90.00"), D("0")),
    ]
    assert p.stats.credit_notes == 1


def test_small_round_off_is_booked_and_flagged_big_gaps_are_errors():
    p = parse_table(sales(
        ["04/04/2025", "A", "X", "", "100", "9", "9", "", "118.40"],
        ["04/04/2025", "B", "X", "", "100", "9", "9", "", "125"],
    ), "sales")
    assert ("Round Off", D("0"), D("0.40")) in lines(p)
    by_row = {i.row_number: i for i in p.result.issues}
    assert by_row[4].severity.value == "WARNING" and by_row[5].severity.value == "ERROR" and "check the row" in by_row[5].message
    assert p.stats.round_off_rows == 1 and p.stats.records == 1 and p.stats.unreadable_rows == 1


def test_gst_sanity_warnings():
    p = parse_table(sales(
        ["01/04/2025", "A", "X", "BADGSTIN", "100", "9", "8", "", "117"],
        ["01/04/2025", "B", "X", "", "100", "9", "9", "18", "136"],
    ), "sales")
    fields = sorted((i.row_number, i.field) for i in p.result.issues)
    assert fields == [(4, "gstin"), (4, "sgst"), (5, "igst")]
    assert all(i.severity.value == "WARNING" for i in p.result.issues)


def test_bad_rows_are_error_vouchers_not_guesses():
    p = parse_table(sales(
        ["not a date", "A", "X", "", "100", "", "", "", ""],
        ["02/04/2025", "B", "", "", "100", "", "", "", ""],
        ["02/04/2025", "C", "X", "", "abc", "", "", "", ""],
    ), "sales")
    assert {(i.row_number, i.field) for i in p.result.issues} == {(4, "date"), (5, "party"), (6, "taxable")}
    assert p.stats.records == 0 and p.stats.unreadable_rows == 3
    assert len(p.result.rows) == 3  # one blocked line each, so they stay visible


def test_total_lines_blank_lines_and_zero_rows_are_left_out():
    p = parse_table(sales(
        ["01/04/2025", "A", "X", "", "100", "", "", "", ""],
        ["", "", "", "", "", "", "", "", ""],
        ["", "Total", "", "", "100", "", "", "", ""],
        ["01/04/2025", "Z", "X", "", "0", "0", "0", "", "0"],
    ), "sales")
    assert p.stats.records == 1 and p.stats.skipped_rows == 2
    assert [i.severity.value for i in p.result.issues] == ["WARNING"]


def test_per_party_accounts_and_custom_names():
    rows = sales(["01/04/2025", "A", "Acme Ltd", "", "100", "", "", "", ""])
    own = parse_table(rows, "sales", {"main": "Domestic Sales"}, party_accounts=True)
    assert [a for a, _, _ in lines(own)] == ["Acme Ltd", "Domestic Sales"]
    control = parse_table(rows, "sales", {"party": "Debtors"})
    assert [a for a, _, _ in lines(control)] == ["Debtors", "Sales"]


def test_a_purchase_bill_is_the_mirror_image():
    p = parse_table(sales(["05/04/2025", "B-9", "Supplier", "", "10,000", "900", "900", "", "11,800"], header=["Bill Date", "Bill No", "Supplier Name", "GSTIN", "Taxable Value", "CGST", "SGST", "IGST", "Bill Amount"]), "purchase")
    assert lines(p) == [
        ("Trade Payables", D("0"), D("11800")),
        ("Purchases", D("10000"), D("0")),
        ("Input CGST", D("900"), D("0")),
        ("Input SGST", D("900"), D("0")),
    ]
    assert p.result.rows[0].description == "Bill B-9 - Supplier"


def test_party_accounts_do_not_apply_to_payroll():
    with pytest.raises(RegisterError):
        parse_table([PAYROLL_HEADER, ["A", "1", "", "", "", "", "", "1"]], "payroll", default_date=date(2025, 4, 30), party_accounts=True)


# ---- payroll -----------------------------------------------------------------------------------------------------------

def payroll(*rows, header=PAYROLL_HEADER):
    return [["Salary Statement - April 2025"], header, *rows]


def test_a_payroll_row_becomes_a_balanced_voucher_on_the_given_date():
    p = parse_table(payroll(["Ravi Kumar", "50,000.00", "1,800.00", "", "2,000", "200", "4,000.00", "46,000.00"]), "payroll", default_date=date(2025, 4, 30))
    assert lines(p) == [
        ("Salaries and Wages", D("50000.00"), D("0")),
        ("PF Payable", D("0"), D("1800.00")),
        ("TDS on Salary Payable", D("0"), D("2000")),
        ("Professional Tax Payable", D("0"), D("200")),
        ("Salary Payable", D("0"), D("46000.00")),
    ]
    assert p.result.rows[0].transaction_date == date(2025, 4, 30) and p.stats.date_from_default == 1
    assert [s["value"] for s in p.stats.summary if s["label"] in ("Gross pay", "Net pay")] == ["50000.00", "46000.00"]


def test_payroll_needs_a_date_from_the_file_or_the_person():
    with pytest.raises(RegisterError) as info:
        parse_table(payroll(["A", "100", "", "", "", "", "", "100"]), "payroll")
    assert "column headings" in str(info.value)
    dated = parse_table([["Employee", "Pay Date", "Gross", "Net"], ["A", "30-04-2025", "100", "100"]], "payroll")
    assert dated.result.rows[0].transaction_date == date(2025, 4, 30) and dated.stats.date_from_default == 0


def test_gross_minus_deductions_must_equal_net():
    p = parse_table(payroll(
        ["Bad", "20000", "1000", "", "", "", "1000", "15000"],
        ["Round", "20000.50", "", "", "", "", "", "20000"],
    ), "payroll", default_date=date(2025, 4, 30))
    by_row = {i.row_number: i for i in p.result.issues}
    assert by_row[3].severity.value == "ERROR" and "net pay is 15000" in by_row[3].message
    assert by_row[4].severity.value == "WARNING"
    # Dr salary 20000.50 = Cr net pay 20000 + Cr round off 0.50
    assert ("Round Off", D("0"), D("0.50")) in lines(p)
    assert p.stats.records == 1 and p.stats.unreadable_rows == 1


def test_net_pay_is_worked_out_when_the_file_has_none():
    p = parse_table([["Employee", "Gross", "PF"], ["A", "1000", "120"]], "payroll", default_date=date(2025, 4, 30))
    assert ("Salary Payable", D("0"), D("880")) in lines(p) and not p.result.issues


def test_only_a_total_deductions_column_is_booked_as_other_deductions():
    p = parse_table([["Employee", "Gross", "Total Deductions", "Net"], ["A", "1000", "100", "900"]], "payroll", default_date=date(2025, 4, 30))
    assert ("Other Salary Deductions Payable", D("0"), D("100")) in lines(p) and not p.result.issues


def test_listed_deductions_that_disagree_with_the_total_column_are_flagged():
    p = parse_table(payroll(["A", "1000", "100", "", "", "", "150", "900"]), "payroll", default_date=date(2025, 4, 30))
    assert [(i.field, i.severity.value) for i in p.result.issues] == [("total_deductions", "WARNING")]


def test_negative_and_nameless_payroll_rows_are_blocked():
    p = parse_table(payroll(["A", "-1000", "", "", "", "", "", "-1000"], ["", "1000", "", "", "", "", "", "1000"]), "payroll", default_date=date(2025, 4, 30))
    assert {(i.row_number, i.severity.value) for i in p.result.issues} == {(3, "ERROR"), (4, "ERROR")}


# ---- the mapping planner turns them into entries ---------------------------------------------------------------------

def test_sales_and_payroll_post_as_balanced_entries():
    s = parse_table(sales(["01/04/2025", "A", "X", "", "10,000", "900", "900", "", "11,800"], ["02/04/2025", "B", "Y", "", "500", "", "", "90", "590"]), "sales")
    plan = plan_of(s)
    assert not plan.blocked and [e.total for e in plan.entries] == [D("11800"), D("590")]
    pay = parse_table(payroll(["Ravi", "50000", "1800", "", "2000", "200", "4000", "46000"]), "payroll", default_date=date(2025, 4, 30))
    plan = plan_of(pay)
    assert not plan.blocked and plan.entries[0].total == D("50000")


def test_error_vouchers_are_blocked_by_the_planner():
    p = parse_table(sales(["01/04/2025", "A", "X", "", "100", "9", "9", "", "500"]), "sales")
    plan = plan_of(p)
    assert len(plan.blocked) == 1 and not plan.entries


# ---- duplicates --------------------------------------------------------------------------------------------------------

def test_identical_rows_in_one_file_are_different_vouchers():
    row = ["01/04/2025", "A", "X", "", "100", "", "", "", ""]
    p = parse_table(sales(row, row), "sales")
    keys = keys_of(p)
    assert len(keys) == 2 and keys[0] != keys[1]


def test_overlapping_files_do_not_post_twice():
    first = parse_table(sales(["01/04/2025", "A", "X", "", "100", "", "", "", ""], ["02/04/2025", "B", "X", "", "200", "", "", "", ""]), "sales")
    second = parse_table(sales(["02/04/2025", "B", "X", "", "200", "", "", "", ""], ["03/04/2025", "C", "X", "", "300", "", "", "", ""]), "sales")
    assert mark_duplicates(second, set(keys_of(first))) == 1
    dup = [i for i in second.result.issues if i.field == "duplicate"]
    assert [i.row_number for i in dup] == [4] and dup[0].severity.value == "ERROR"
    assert second.stats.duplicates == 1


def test_a_file_imported_twice_is_refused_and_other_registers_are_not_confused():
    p = parse_table(sales(["01/04/2025", "A", "X", "", "100", "", "", "", ""]), "sales")
    with pytest.raises(RegisterError) as info:
        mark_duplicates(p, set(keys_of(p)))
    assert "already imported" in str(info.value)
    same_rows_as_purchase = parse_table(sales(["01/04/2025", "A", "X", "", "100", "", "", "", ""]), "purchase")
    assert not set(keys_of(same_rows_as_purchase)) & set(keys_of(p))
    assert mark_duplicates(p, set()) == 0


# ---- files and limits --------------------------------------------------------------------------------------------------

def test_excel_register_with_real_dates_and_numbers(tmp_path: Path):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["Purchase Register"])
    ws.append(["Bill Date", "Bill No", "Supplier", "Taxable Value", "CGST", "SGST", "Total"])
    ws.append([datetime(2025, 4, 5), "B-1", "Vendor", 1000.5, 90.05, 90.05, 1180.6])
    path = tmp_path / "p.xlsx"
    wb.save(path)
    p = parse_file(path, "purchase")
    assert p.result.source_format == "register-xlsx" and p.stats.records == 1 and not p.result.issues
    assert ("Purchases", D("1000.5"), D("0")) in lines(p)


def test_csv_register_and_unsupported_files(tmp_path: Path):
    path = tmp_path / "s.csv"
    path.write_text("Date,Customer,Taxable Value,CGST,SGST\n01-04-2025,Acme,\"1,000.00\",90,90\n", encoding="utf-8")
    assert parse_file(path, "sales").stats.records == 1
    bad = tmp_path / "s.xls"
    bad.write_bytes(b"x")
    with pytest.raises(RegisterError) as info:
        parse_file(bad, "sales")
    assert "Save As .xlsx" in str(info.value)


def test_a_file_too_long_for_the_numbering_is_refused():
    rows = sales(["01/04/2025", "A", "X", "", "5", "", "", "", ""]) + [[]] * LINE_ROW_OFFSET + [["01/04/2025", "B", "X", "", "5", "", "", "", ""]]
    with pytest.raises(RegisterError) as info:
        parse_table(rows, "sales")
    assert "too many rows" in str(info.value)


def test_account_names_are_validated():
    for bad in ("", "x" * 151, "a\x00b"):
        with pytest.raises(ValueError):
            parse_table(sales(["01/04/2025", "A", "X", "", "5", "", "", "", ""]), "sales", {"main": bad} if bad else {"main": " "})


# ---- the command line --------------------------------------------------------------------------------------------------

def write_csv(tmp_path: Path, lines_: list[str]) -> str:
    path = tmp_path / "r.csv"
    path.write_text("\n".join(lines_) + "\n", encoding="utf-8")
    return str(path)


def test_templates_command(capsys):
    assert cli.main(["x", "templates"]) == 0
    assert {t["key"] for t in json.loads(capsys.readouterr().out)["templates"]} == {"sales", "purchase", "payroll"}


def test_preview_reports_everything_and_saves_nothing(tmp_path, monkeypatch, capsys):
    saved = []
    monkeypatch.setattr(cli, "existing_keys", lambda firm, company, keys: set())
    monkeypatch.setattr(cli, "persist_parse_result", lambda **kw: saved.append(kw))
    path = write_csv(tmp_path, ["Date,Customer,Taxable Value,CGST,SGST", "01-04-2025,Acme,1000,90,90"])
    assert cli.main(["x", "preview", "sales", path, '{"main": "Domestic Sales"}', "-", "0", "f", "c"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["preview"] is True and out["rows"] == 4 and out["errors"] == 0 and out["total_debit"] == out["total_credit"] == "1180"
    assert out["register"]["template"] == "sales" and out["register"]["records"] == 1 and saved == []


def test_import_saves_with_a_reference_tag_from_the_file_id(tmp_path, monkeypatch, capsys):
    saved = []
    monkeypatch.setattr(cli, "existing_keys", lambda firm, company, keys: set())
    monkeypatch.setattr(cli, "persist_parse_result", lambda **kw: saved.append(kw))
    path = write_csv(tmp_path, ["Employee,Gross,Net", "A,1000,1000"])
    assert cli.main(["x", "import", "payroll", path, "{}", "2025-04-30", "0", "f", "c", "abcdef12-0000"]) == 0
    assert json.loads(capsys.readouterr().out)["preview"] is False
    assert saved[0]["source_file_id"] == "abcdef12-0000"
    assert {r.reference for r in saved[0]["result"].rows} == {"RG-abcdef-2"}


def test_cli_errors_are_400_for_the_person_and_500_for_the_unexpected(tmp_path, monkeypatch, capsys):
    path = write_csv(tmp_path, ["a,b", "1,2"])
    for args in (["sales", path, "{}", "-", "0", "f", "c"], ["sales", path, "not json", "-", "0", "f", "c"], ["sales", path, "{}", "31/03", "0", "f", "c"]):
        assert cli.main(["x", "preview", *args]) == 1
        assert json.loads(capsys.readouterr().err)["status"] == 400
    monkeypatch.setattr(cli, "parse_file", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert cli.main(["x", "preview", "sales", path, "{}", "-", "0", "f", "c"]) == 1
    err = json.loads(capsys.readouterr().err)
    assert err["status"] == 500 and err["error"] == "boom"
    assert cli.main(["x", "nonsense"]) == 1