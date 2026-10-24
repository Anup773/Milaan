"""Bank statement connector: layouts, dates and amounts, the running-balance check, duplicates, files, and the command line."""
from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from engine.bank import cli
from engine.bank.statement import (
    COUNTER_ROW_OFFSET,
    BankError,
    detect_layout,
    keys_of,
    mark_duplicates,
    parse_file,
    parse_table,
    read_amount,
    read_date,
)
from engine.mapping.planner import Period, SourceRow, plan_entries

BANK, SUSPENSE = "HDFC Bank", "Bank Statement Suspense"

HDFC_HEADER = ["Date", "Narration", "Chq./Ref.No.", "Value Dt", "Withdrawal Amt.", "Deposit Amt.", "Closing Balance"]


def hdfc(rows):
    return [["HDFC BANK LTD"], ["Statement of account"], [], HDFC_HEADER, *rows]


def parse(rows, **kw):
    return parse_table(rows, kw.get("bank", BANK), kw.get("suspense", SUSPENSE), ref_tag=kw.get("tag", "BS"))


# ---- columns ---------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize(
    "header",
    [
        HDFC_HEADER,
        ["Txn Date", "Value Date", "Description", "Ref No./Cheque No.", "Debit", "Credit", "Balance"],  # SBI
        ["Transaction Date", "Value Date", "Description", "Ref No./Cheque No.", "Debit", "Credit", "Balance"],  # ICICI
        ["Tran Date", "CHQNO", "PARTICULARS", "DR", "CR", "BAL", "SOL"],  # Axis
        ["Date", "Details", "Amount", "Dr/Cr", "Balance"],
    ],
)
def test_common_bank_headings_are_recognised(header):
    assert detect_layout(header).is_usable


def test_the_transaction_date_wins_over_the_value_date():
    layout = detect_layout(["Value Date", "Txn Date", "Description", "Debit", "Credit"])
    assert layout.columns["date"] == 1


def test_not_a_statement_is_a_clear_error():
    with pytest.raises(BankError) as info:
        parse([["Name", "Age"], ["a", "1"]])
    assert "column headings" in str(info.value)


# ---- dates and amounts -----------------------------------------------------------------------------------------------

@pytest.mark.parametrize(
    "value, expected",
    [
        ("01/04/25", date(2025, 4, 1)),
        ("31-03-2026", date(2026, 3, 31)),
        ("04/05/2025", date(2025, 5, 4)),  # day first
        ("01 Apr 2025", date(2025, 4, 1)),
        ("01-Apr-25", date(2025, 4, 1)),
        ("2025-04-01 10:15:00", date(2025, 4, 1)),
        ("01/04/2025 10:15 PM", date(2025, 4, 1)),
        (datetime(2025, 4, 1, 0, 0), date(2025, 4, 1)),
        ("", None),
        ("garbage", None),
        (45748, None),
    ],
)
def test_dates(value, expected):
    assert read_date(value) == expected


@pytest.mark.parametrize(
    "value, expected",
    [
        ("1,20,000.50", Decimal("120000.50")),
        ("(500)", Decimal("-500")),
        ("1,000.00 Cr", Decimal("1000.00")),
        ("1,000.00 Dr", Decimal("-1000.00")),
        ("", Decimal("0")),
        ("-", Decimal("0")),
        (1234.5, Decimal("1234.5")),
        (7, Decimal("7")),
    ],
)
def test_amounts(value, expected):
    assert read_amount(value) == expected


def test_unreadable_amount_raises():
    with pytest.raises(ValueError):
        read_amount("abc")


# ---- turning transactions into balanced pairs ------------------------------------------------------------------------

def test_each_transaction_becomes_a_balanced_pair_with_the_right_sides():
    p = parse(hdfc([
        ["01/04/25", "UPI-RENT", "123456", "01/04/25", "10,000.00", "", "40,000.00"],
        ["02/04/25", "NEFT-CUSTOMER A", "N1", "02/04/25", "", "25,000.50", "65,000.50"],
    ]))
    rows = [(r.row_number, r.account_ref, r.debit, r.credit, r.reference) for r in p.result.rows]
    assert rows == [
        (5, BANK, Decimal("0"), Decimal("10000.00"), "BS-5"),
        (5 + COUNTER_ROW_OFFSET, SUSPENSE, Decimal("10000.00"), Decimal("0"), "BS-5"),
        (6, BANK, Decimal("25000.50"), Decimal("0"), "BS-6"),
        (6 + COUNTER_ROW_OFFSET, SUSPENSE, Decimal("0"), Decimal("25000.50"), "BS-6"),
    ]
    assert p.result.total_debit == p.result.total_credit == Decimal("35000.50")
    assert "[Ref 123456]" in p.result.rows[0].description and p.result.rows[0].transaction_date == date(2025, 4, 1)
    assert not p.result.issues
    assert p.stats.deposits == 1 and p.stats.withdrawals == 1
    assert p.stats.total_deposits == Decimal("25000.50") and p.stats.total_withdrawals == Decimal("10000.00")


def test_rows_post_as_balanced_entries_through_the_real_mapping_planner():
    p = parse(hdfc([
        ["01/04/25", "UPI-RENT", "", "", "10,000.00", "", ""],
        ["01/04/25", "UPI-SHOP", "", "", "500.00", "", ""],  # same day, same (blank) bank reference: still two entries
    ]))
    rows = [SourceRow(str(i), r.row_number, r.account_ref, r.transaction_date, r.description, r.debit, r.credit, r.reference, "OK") for i, r in enumerate(p.result.rows)]
    mapping = {"hdfc bank": "A1", "bank statement suspense": "A2"}
    plan = plan_entries(rows, mapping, [Period("P1", "FY26", date(2025, 4, 1), date(2026, 3, 31), False)])
    assert not plan.blocked and len(plan.entries) == 2
    assert [e.total for e in plan.entries] == [Decimal("10000.00"), Decimal("500.00")]


def test_single_amount_column_with_dr_cr_marker_or_sign():
    with_marker = parse([["Date", "Details", "Amount", "Dr/Cr", "Balance"], ["01-04-2025", "A", "100.00", "Dr", ""], ["01-04-2025", "B", "250.00", "Cr", ""]])
    assert [(r.account_ref, r.debit, r.credit) for r in with_marker.result.rows if r.account_ref == BANK] == [(BANK, Decimal("0"), Decimal("100.00")), (BANK, Decimal("250.00"), Decimal("0"))]
    signed = parse([["Date", "Details", "Amount"], ["01-04-2025", "A", "-100.00"], ["01-04-2025", "B", "250.00"]])
    assert signed.stats.total_withdrawals == Decimal("100.00") and signed.stats.total_deposits == Decimal("250.00")


def test_unknown_dr_cr_marker_is_an_error_row_not_a_guess():
    p = parse([["Date", "Details", "Amount", "Dr/Cr"], ["01-04-2025", "A", "100.00", "??"]])
    assert [i.field for i in p.result.issues if i.severity.value == "ERROR"] == ["type"]
    assert p.stats.transactions == 0 and p.stats.unreadable_rows == 1


def test_opening_balance_row_wrapped_narration_and_total_rows():
    p = parse(hdfc([
        ["01/04/25", "OPENING BALANCE", "", "", "", "", "50,000.00"],
        ["01/04/25", "UPI-RENT PAYMENT FOR", "1", "", "10,000.00", "", "40,000.00"],
        ["", "THE OFFICE", "", "", "", "", ""],
        ["", "TOTAL", "", "", "10,000.00", "", ""],
        ["", "", "", "", "", "", ""],
    ]))
    assert p.stats.transactions == 1 and p.stats.opening_balance == Decimal("50000.00") and p.stats.closing_balance == Decimal("40000.00")
    assert p.result.rows[0].description.startswith("UPI-RENT PAYMENT FOR THE OFFICE")
    assert p.stats.balance_check == "passed" and not p.result.issues


def test_cheque_numbers_stored_as_floats_lose_the_dot_zero():
    p = parse(hdfc([["01/04/25", "CHEQUE", 123456.0, "", 100, "", ""]]))
    assert "[Ref 123456]" in p.result.rows[0].description


# ---- the running balance ---------------------------------------------------------------------------------------------

def test_balance_check_passes_and_fails_loudly():
    good = parse(hdfc([
        ["01/04/25", "A", "", "", "100", "", "900"],
        ["02/04/25", "B", "", "", "", "50", "950"],
    ]))
    assert good.stats.balance_check == "passed" and good.stats.opening_balance == Decimal("1000")
    bad = parse(hdfc([
        ["01/04/25", "A", "", "", "100", "", "900"],
        ["02/04/25", "B", "", "", "", "50", "999"],
        ["03/04/25", "C", "", "", "10", "", "989"],  # consistent with the bank's own 999, so reported once, not again
    ]))
    assert bad.stats.balance_check == "failed" and bad.stats.balance_mismatches == 1
    warning = [i for i in bad.result.issues if i.field == "balance"]
    assert len(warning) == 1 and warning[0].row_number == 6 and warning[0].severity.value == "WARNING"
    assert "should give 950" in warning[0].message


def test_newest_first_statements_are_checked_in_true_order():
    ok = parse(hdfc([
        ["03/04/25", "C", "", "", "", "50", "950"],
        ["02/04/25", "B", "", "", "100", "", "900"],
        ["01/04/25", "A", "", "", "", "100", "1000"],
    ]))
    assert ok.stats.order == "newest_first" and ok.stats.balance_check == "passed"
    assert ok.stats.opening_balance == Decimal("900") and ok.stats.closing_balance == Decimal("950")
    wrong = parse(hdfc([
        ["03/04/25", "C", "", "", "", "50", "960"],  # should be 950
        ["02/04/25", "B", "", "", "100", "", "900"],
        ["01/04/25", "A", "", "", "", "100", "1000"],
    ]))
    assert wrong.stats.balance_check == "failed" and [i.row_number for i in wrong.result.issues if i.field == "balance"] == [5]


def test_no_balance_column_means_not_checked_not_passed():
    p = parse([["Date", "Description", "Debit", "Credit"], ["01-04-2025", "A", "10", ""]])
    assert p.stats.balance_check == "not_checked" and p.stats.opening_balance is None


def test_balance_with_cr_dr_suffix():
    p = parse(hdfc([
        ["01/04/25", "A", "", "", "100", "", "900.00 Cr"],
        ["02/04/25", "B", "", "", "", "50", "950.00 Cr"],
    ]))
    assert p.stats.balance_check == "passed"


# ---- rows that cannot be read are never dropped or guessed -------------------------------------------------------------

def test_bad_rows_become_error_pairs_that_the_planner_will_block():
    p = parse(hdfc([
        ["not a date", "A", "", "", "100", "", ""],
        ["02/04/25", "B", "", "", "abc", "", ""],
        ["03/04/25", "C", "", "", "10", "20", ""],
        ["04/04/25", "D", "", "", "-5", "", ""],
        ["05/04/25", "E", "", "", "10", "", ""],
    ]))
    errors = {i.row_number for i in p.result.issues if i.severity.value == "ERROR"}
    assert errors == {5, 6, 7, 8}
    assert p.stats.unreadable_rows == 4 and p.stats.transactions == 1
    assert len(p.result.rows) == 10  # every row is kept, two lines each


def test_every_line_gets_its_own_row_number_because_the_database_requires_it():
    p = parse(hdfc([["01/04/25", "A", "", "", "5", "", ""], ["02/04/25", "B", "", "", "", "7", ""]]))
    numbers = [r.row_number for r in p.result.rows]
    assert len(numbers) == len(set(numbers)) == 4


def test_a_statement_too_long_for_the_numbering_is_refused():
    rows = hdfc([["01/04/25", "A", "", "", "5", "", ""]] + [[]] * COUNTER_ROW_OFFSET + [["01/04/25", "B", "", "", "5", "", ""]])
    with pytest.raises(BankError) as info:
        parse(rows)
    assert "too many rows" in str(info.value)


def test_zero_amount_row_is_a_warning_and_posts_nothing():
    p = parse(hdfc([["01/04/25", "A", "", "", "0.00", "", ""], ["01/04/25", "B", "", "", "5", "", ""]]))
    assert p.stats.transactions == 1 and [i.severity.value for i in p.result.issues] == ["WARNING"]


def test_headings_but_no_transactions():
    with pytest.raises(BankError) as info:
        parse(hdfc([]))
    assert "no transactions" in str(info.value)


@pytest.mark.parametrize("bank, suspense", [("", SUSPENSE), (BANK, " "), (BANK, "hdfc BANK"), ("x" * 151, SUSPENSE), ("a\x00b", SUSPENSE)])
def test_account_names_are_validated(bank, suspense):
    with pytest.raises(BankError):
        parse(hdfc([["01/04/25", "A", "", "", "5", "", ""]]), bank=bank, suspense=suspense)


# ---- duplicates ------------------------------------------------------------------------------------------------------

def test_identical_rows_in_one_file_are_different_transactions():
    p = parse(hdfc([["01/04/25", "ATM", "", "", "100", "", ""], ["01/04/25", "ATM", "", "", "100", "", ""]]))
    keys = keys_of(p)
    assert len(keys) == 2 and keys[0] != keys[1]


def test_overlapping_statements_do_not_post_twice():
    first = parse(hdfc([["01/04/25", "A", "", "", "100", "", "900"], ["02/04/25", "B", "", "", "", "50", "950"]]))
    second = parse(hdfc([["02/04/25", "B", "", "", "", "50", "950"], ["03/04/25", "C", "", "", "10", "", "940"]]))
    assert mark_duplicates(second, set(keys_of(first))) == 1
    dup = [i for i in second.result.issues if i.field == "duplicate"]
    assert [i.row_number for i in dup] == [5] and dup[0].severity.value == "ERROR"
    assert second.stats.duplicates == 1


def test_a_statement_imported_twice_is_refused():
    p = parse(hdfc([["01/04/25", "A", "", "", "100", "", "900"]]))
    with pytest.raises(BankError) as info:
        mark_duplicates(p, set(keys_of(p)))
    assert "already imported" in str(info.value)


def test_another_bank_account_is_not_a_duplicate():
    rows = hdfc([["01/04/25", "A", "", "", "100", "", "900"]])
    assert not set(keys_of(parse(rows, bank="ICICI Bank"))) & set(keys_of(parse(rows)))


def test_no_existing_keys_means_no_duplicates():
    p = parse(hdfc([["01/04/25", "A", "", "", "100", "", ""]]))
    assert mark_duplicates(p, set()) == 0


# ---- files -----------------------------------------------------------------------------------------------------------

def test_csv_file_with_semicolons_and_windows_encoding(tmp_path: Path):
    path = tmp_path / "stmt.csv"
    path.write_bytes("Date;Narration;Debit;Credit;Balance\n01-04-2025;Café ₹ payment;100,00;;900\n".replace("100,00", "100.00").encode("cp1252", errors="replace"))
    p = parse_file(path, BANK, SUSPENSE)
    assert p.stats.transactions == 1 and p.stats.total_withdrawals == Decimal("100.00") and p.result.source_format == "bank-csv"


def test_excel_file_with_real_dates_and_numbers(tmp_path: Path):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["Statement for account 1234"])
    ws.append(["Date", "Narration", "Withdrawal Amt.", "Deposit Amt.", "Closing Balance"])
    ws.append([datetime(2025, 4, 1), "RENT", 10000.5, None, 89999.5])
    ws.append([datetime(2025, 4, 2), "SALES", None, 500, 90499.5])
    path = tmp_path / "stmt.xlsx"
    wb.save(path)
    p = parse_file(path, BANK, SUSPENSE)
    assert p.result.source_format == "bank-xlsx" and p.stats.balance_check == "passed"
    assert p.stats.total_withdrawals == Decimal("10000.5") and p.stats.opening_balance == Decimal("100000.0")


@pytest.mark.parametrize("name, fragment", [("a.xls", "Save As .xlsx"), ("a.pdf", "unsupported file type"), ("a.txt", "unsupported file type")])
def test_unsupported_files_say_what_to_do(tmp_path: Path, name, fragment):
    path = tmp_path / name
    path.write_bytes(b"x")
    with pytest.raises(BankError) as info:
        parse_file(path, BANK, SUSPENSE)
    assert fragment in str(info.value)


def test_a_broken_xlsx_is_explained(tmp_path: Path):
    path = tmp_path / "broken.xlsx"
    path.write_bytes(b"not a zip")
    with pytest.raises(BankError) as info:
        parse_file(path, BANK, SUSPENSE)
    assert "could not be opened" in str(info.value)


# ---- the command line ------------------------------------------------------------------------------------------------

def write_csv(tmp_path: Path, lines: list[str]) -> str:
    path = tmp_path / "s.csv"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


def test_preview_reports_everything_and_saves_nothing(tmp_path, monkeypatch, capsys):
    saved = []
    monkeypatch.setattr(cli, "existing_keys", lambda firm, company, keys: set())
    monkeypatch.setattr(cli, "persist_parse_result", lambda **kw: saved.append(kw))
    path = write_csv(tmp_path, ["Date,Narration,Withdrawal Amt.,Deposit Amt.,Closing Balance", "01/04/25,A,100,,900", "02/04/25,B,,50,950"])
    assert cli.main(["x", "preview", path, BANK, SUSPENSE, "f", "c"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["preview"] is True and out["rows"] == 4 and out["errors"] == 0 and out["total_debit"] == out["total_credit"]
    assert out["bank"]["balance_check"] == "passed" and out["bank"]["transactions"] == 2
    assert saved == []


def test_import_saves_with_a_reference_tag_from_the_file_id(tmp_path, monkeypatch, capsys):
    saved = []
    monkeypatch.setattr(cli, "existing_keys", lambda firm, company, keys: set())
    monkeypatch.setattr(cli, "persist_parse_result", lambda **kw: saved.append(kw))
    path = write_csv(tmp_path, ["Date,Narration,Debit,Credit", "01/04/25,A,100,"])
    assert cli.main(["x", "import", path, BANK, SUSPENSE, "f", "c", "abcdef12-0000"]) == 0
    assert json.loads(capsys.readouterr().out)["preview"] is False
    assert saved[0]["source_file_id"] == "abcdef12-0000"
    assert {r.reference for r in saved[0]["result"].rows} == {"BS-abcdef-2"}


def test_already_imported_rows_come_back_as_errors_in_the_summary(tmp_path, monkeypatch, capsys):
    rows = hdfc([["01/04/25", "A", "", "", "100", "", "900"], ["02/04/25", "B", "", "", "", "50", "950"]])
    earlier = parse(rows)
    monkeypatch.setattr(cli, "existing_keys", lambda firm, company, keys: {earlier.transactions[0].key} & set(keys))
    # the same transactions as a CSV file: row numbers differ, but the fingerprint only uses the content
    path = write_csv(tmp_path, [",".join(str(c) for c in r) for r in rows[3:]])
    assert cli.main(["x", "preview", path, BANK, SUSPENSE, "f", "c"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["bank"]["duplicates"] == 1 and out["errors"] == 1 and out["issues"][0]["field"] == "duplicate"


def test_cli_errors_are_400_for_the_person_and_500_for_the_unexpected(tmp_path, monkeypatch, capsys):
    path = write_csv(tmp_path, ["a,b", "1,2"])
    assert cli.main(["x", "preview", path, BANK, SUSPENSE, "f", "c"]) == 1
    assert json.loads(capsys.readouterr().err)["status"] == 400
    monkeypatch.setattr(cli, "parse_file", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert cli.main(["x", "preview", path, BANK, SUSPENSE, "f", "c"]) == 1
    err = json.loads(capsys.readouterr().err)
    assert err["status"] == 500 and err["error"] == "boom"
    assert cli.main(["x", "nonsense"]) == 1