"""Tally connector: XML parsing rules and the HTTP client, against a mock Tally server (no real Tally needed)."""
from __future__ import annotations

import threading
from datetime import date
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from engine.tally import client
from engine.tally.cli import main as cli_main
from engine.tally.parser import TallyError, decode_xml_bytes, parse_tally_xml


def voucher(vtype="Payment", number="1", date_="20250415", entries=(), narration="", extra="", inner_tag="ALLLEDGERENTRIES.LIST"):
    lines = "".join(
        f"<{inner_tag}><LEDGERNAME>{name}</LEDGERNAME><ISDEEMEDPOSITIVE>{'Yes' if amt.startswith('-') else 'No'}</ISDEEMEDPOSITIVE>"
        f"<AMOUNT>{amt}</AMOUNT></{inner_tag}>"
        for name, amt in entries
    )
    return (
        f'<TALLYMESSAGE><VOUCHER VCHTYPE="{vtype}" ACTION="Create">'
        f"<DATE>{date_}</DATE><VOUCHERTYPENAME>{vtype}</VOUCHERTYPENAME><VOUCHERNUMBER>{number}</VOUCHERNUMBER>"
        f"<NARRATION>{narration}</NARRATION>{extra}{lines}</VOUCHER></TALLYMESSAGE>"
    )


def envelope(*vouchers):
    return "<ENVELOPE><BODY><IMPORTDATA><REQUESTDATA>" + "".join(vouchers) + "</REQUESTDATA></IMPORTDATA></BODY></ENVELOPE>"


def test_debit_is_negative_credit_is_positive():
    xml = envelope(voucher(entries=[("Rent", "-5000.00"), ("HDFC Bank", "5000.00")], narration="April rent"))
    parsed = parse_tally_xml(xml)
    rows = parsed.result.rows
    assert [(r.account_ref, r.debit, r.credit) for r in rows] == [
        ("Rent", Decimal("5000.00"), Decimal("0")),
        ("HDFC Bank", Decimal("0"), Decimal("5000.00")),
    ]
    assert rows[0].transaction_date == date(2025, 4, 15)
    assert rows[0].reference == "Payment 1"
    assert rows[0].description == "April rent"
    assert not parsed.result.issues
    assert parsed.result.total_debit == parsed.result.total_credit == Decimal("5000.00")


def test_same_number_on_different_voucher_types_stays_separate():
    xml = envelope(
        voucher("Payment", "1", entries=[("Rent", "-100"), ("Bank", "100")]),
        voucher("Receipt", "1", entries=[("Bank", "-200"), ("Debtors", "200")]),
    )
    refs = {r.reference for r in parse_tally_xml(xml).result.rows}
    assert refs == {"Payment 1", "Receipt 1"}


def test_item_invoice_reads_sales_ledger_inside_stock_lines():
    xml = envelope(
        "<TALLYMESSAGE><VOUCHER VCHTYPE='Sales'><DATE>20250501</DATE><VOUCHERNUMBER>S-7</VOUCHERNUMBER>"
        "<LEDGERENTRIES.LIST><LEDGERNAME>Customer A</LEDGERNAME><AMOUNT>-118.00</AMOUNT></LEDGERENTRIES.LIST>"
        "<LEDGERENTRIES.LIST><LEDGERNAME>Output GST</LEDGERNAME><AMOUNT>18.00</AMOUNT></LEDGERENTRIES.LIST>"
        "<ALLINVENTORYENTRIES.LIST><STOCKITEMNAME>Widget</STOCKITEMNAME><AMOUNT>100.00</AMOUNT>"
        "<ACCOUNTINGALLOCATIONS.LIST><LEDGERNAME>Sales</LEDGERNAME><AMOUNT>100.00</AMOUNT></ACCOUNTINGALLOCATIONS.LIST>"
        "</ALLINVENTORYENTRIES.LIST></VOUCHER></TALLYMESSAGE>"
    )
    parsed = parse_tally_xml(xml)
    assert sorted(r.account_ref for r in parsed.result.rows) == ["Customer A", "Output GST", "Sales"]
    assert parsed.result.total_debit == parsed.result.total_credit == Decimal("118.00")
    assert parsed.stats.unbalanced_vouchers == 0


def test_cancelled_optional_and_order_vouchers_are_skipped_and_counted():
    xml = envelope(
        voucher(entries=[("Rent", "-100"), ("Bank", "100")], number="1"),
        voucher(entries=[("Rent", "-999"), ("Bank", "999")], number="2", extra="<ISCANCELLED>Yes</ISCANCELLED>"),
        voucher(entries=[("Rent", "-888"), ("Bank", "888")], number="3", extra="<ISOPTIONAL>Yes</ISOPTIONAL>"),
        voucher("Sales Order", "9", entries=[("Customer", "-500"), ("Sales", "500")]),
    )
    parsed = parse_tally_xml(xml)
    assert len(parsed.result.rows) == 2
    s = parsed.stats
    assert (s.vouchers_seen, s.vouchers_imported, s.skipped_cancelled, s.skipped_optional, s.skipped_non_accounting) == (4, 1, 1, 1, 1)


def test_unbalanced_voucher_gets_an_error_on_every_row():
    xml = envelope(voucher(entries=[("Rent", "-100"), ("Bank", "90")]))
    parsed = parse_tally_xml(xml)
    assert parsed.stats.unbalanced_vouchers == 1
    errors = [i for i in parsed.result.issues if i.severity.value == "ERROR"]
    assert len(errors) == 2 and "does not balance" in errors[0].message


def test_zero_amount_lines_are_skipped_but_counted():
    xml = envelope(voucher(entries=[("Rent", "-100"), ("Bank", "100"), ("Nothing", "0.00")]))
    parsed = parse_tally_xml(xml)
    assert len(parsed.result.rows) == 2 and parsed.stats.zero_amount_lines_skipped == 1


def test_missing_voucher_number_gets_a_unique_reference():
    xml = envelope(
        voucher(number="", entries=[("A", "-1"), ("B", "1")]),
        voucher(number="", entries=[("A", "-2"), ("B", "2")]),
    )
    refs = [r.reference for r in parse_tally_xml(xml).result.rows]
    assert len(set(refs)) == 2


def test_bad_character_reference_from_tally_does_not_break_parsing():
    xml = envelope(voucher(entries=[("Rent&#4; Ltd", "-100"), ("Bank", "100")]))
    rows = parse_tally_xml(xml).result.rows
    assert rows[0].account_ref == "Rent Ltd"


def test_utf16_export_is_read():
    xml = envelope(voucher(entries=[("Rent", "-100"), ("Bank", "100")]))
    data = ('<?xml version="1.0" encoding="UTF-16"?>' + xml).encode("utf-16")
    assert len(parse_tally_xml(data).result.rows) == 2
    assert "Rent" in decode_xml_bytes(data)


def test_decimals_stay_exact():
    xml = envelope(voucher(entries=[("A", "-0.10"), ("B", "0.10")]) + voucher(number="2", entries=[("A", "-0.20"), ("B", "0.20")]))
    assert parse_tally_xml(xml).result.total_debit == Decimal("0.30")


@pytest.mark.parametrize(
    "bad,fragment",
    [
        ("", "empty"),
        ("not xml at all", "not valid XML"),
        ("<ENVELOPE><BODY></BODY></ENVELOPE>", "no vouchers"),
        ('<!DOCTYPE x [<!ENTITY a "b">]><ENVELOPE/>', "DOCTYPE"),
        ("<RESPONSE><LINEERROR>Company not open</LINEERROR></RESPONSE>", "Company not open"),
    ],
)
def test_unusable_input_is_a_clear_error(bad, fragment):
    with pytest.raises(TallyError) as info:
        parse_tally_xml(bad)
    assert fragment in str(info.value)


def test_only_cancelled_vouchers_is_an_error_not_an_empty_success():
    xml = envelope(voucher(entries=[("A", "-1"), ("B", "1")], extra="<ISCANCELLED>Yes</ISCANCELLED>"))
    with pytest.raises(TallyError) as info:
        parse_tally_xml(xml)
    assert "none could be imported" in str(info.value)


# -- the HTTP client, against a mock Tally -----------------------------------------------------

COMPANIES_XML = "<ENVELOPE><BODY><DATA><COLLECTION><COMPANY NAME='Acme Traders'/><COMPANY><NAME>Beta Co</NAME></COMPANY></COLLECTION></DATA></BODY></ENVELOPE>"
DAYBOOK_XML = envelope(voucher(entries=[("Rent", "-100"), ("Bank", "100")]))


class MockTally(BaseHTTPRequestHandler):
    seen: list[str] = []

    def do_POST(self):  # noqa: N802
        body = self.rfile.read(int(self.headers.get("Content-Length", "0"))).decode("utf-8")
        MockTally.seen.append(body)
        out = COMPANIES_XML if "List of Companies" in body else DAYBOOK_XML
        data = out.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):  # silence
        pass


@pytest.fixture()
def mock_tally(monkeypatch):
    server = HTTPServer(("127.0.0.1", 0), MockTally)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    MockTally.seen = []
    monkeypatch.setenv("TALLY_URL", f"http://127.0.0.1:{server.server_port}")
    yield server
    server.shutdown()


def test_lists_companies_from_both_xml_shapes(mock_tally):
    assert client.list_companies() == ["Acme Traders", "Beta Co"]


def test_day_book_request_carries_dates_and_company_and_escapes_it(mock_tally):
    body = client.fetch_day_book(date(2025, 4, 1), date(2026, 3, 31), "A & B <Ltd>")
    assert b"<VOUCHER" in body
    sent = MockTally.seen[-1]
    assert "<SVFROMDATE>20250401</SVFROMDATE>" in sent and "<SVTODATE>20260331</SVTODATE>" in sent
    assert "<SVCURRENTCOMPANY>A &amp; B &lt;Ltd&gt;</SVCURRENTCOMPANY>" in sent
    assert "<ID>Day Book</ID>" in sent


def test_end_before_start_is_rejected():
    with pytest.raises(TallyError):
        client.fetch_day_book(date(2026, 1, 1), date(2025, 1, 1))


def test_unreachable_tally_gives_a_helpful_message(monkeypatch):
    monkeypatch.setenv("TALLY_URL", "http://127.0.0.1:1")
    with pytest.raises(TallyError) as info:
        client.list_companies()
    assert "cannot reach Tally" in str(info.value)


def test_bad_tally_url_is_refused(monkeypatch):
    monkeypatch.setenv("TALLY_URL", "file:///etc/passwd")
    with pytest.raises(TallyError):
        client.tally_url()


def test_status_command_never_fails_when_tally_is_down(monkeypatch, capsys):
    monkeypatch.setenv("TALLY_URL", "http://127.0.0.1:1")
    assert cli_main(["x", "status"]) == 0
    out = capsys.readouterr().out
    assert '"reachable": false' in out


def test_cli_reports_bad_input_as_400(tmp_path, capsys):
    bad = tmp_path / "x.xml"
    bad.write_text("not xml")
    assert cli_main(["x", "import-file", str(bad), "f", "c", "s"]) == 1
    assert '"status": 400' in capsys.readouterr().err