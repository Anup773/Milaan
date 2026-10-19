"""Google Sheets connector, tested against a mock Google (token, Sheets API and CSV export). No real Google needed."""
from __future__ import annotations

import base64
import json
import threading
import urllib.parse
from datetime import date
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from engine.sheets import client
from engine.sheets.cli import main as cli_main
from engine.sheets.parser import parse_rows, serial_to_date
from engine.sheets.source import SheetsError, parse_sheet_reference

GOOD_ID = "1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789_-abcde"
PRIVATE_ID = "1PRIVATEprivatePRIVATEprivate0123456789"
NOSHARE_ID = "1NOSHAREnoshareNOSHAREnoshare0123456789"
MISSING_ID = "1MISSINGmissingMISSINGmissing0123456789"


# ---- pasted links -------------------------------------------------------------------------------------------------

def test_full_link_with_tab_number():
    ref = parse_sheet_reference(f"https://docs.google.com/spreadsheets/d/{GOOD_ID}/edit#gid=1234567")
    assert (ref.sheet_id, ref.gid) == (GOOD_ID, 1234567)


def test_link_with_gid_in_query_and_account_prefix():
    ref = parse_sheet_reference(f"https://docs.google.com/spreadsheets/u/1/d/{GOOD_ID}/edit?gid=9&usp=sharing")
    assert (ref.sheet_id, ref.gid) == (GOOD_ID, 9)


def test_bare_id_and_link_without_tab():
    assert parse_sheet_reference(GOOD_ID).gid is None
    assert parse_sheet_reference(f"docs.google.com/spreadsheets/d/{GOOD_ID}/edit").gid is None


@pytest.mark.parametrize(
    "bad",
    ["", "   ", "short", "https://evil.example.com/spreadsheets/d/" + GOOD_ID, "http://localhost:4000/x", "https://docs.google.com/document/d/" + GOOD_ID, "https://docs.google.com.evil.com/spreadsheets/d/" + GOOD_ID],
)
def test_anything_that_is_not_a_sheets_link_is_refused(bad):
    with pytest.raises(SheetsError):
        parse_sheet_reference(bad)


# ---- turning cells into rows --------------------------------------------------------------------------------------

def test_serial_dates_become_exact_dates():
    assert serial_to_date(45748) == date(2025, 4, 1)
    assert serial_to_date(46112) == date(2026, 3, 31)
    assert serial_to_date(0) is None and serial_to_date(9_999_999) is None and serial_to_date(True) is None


def test_rows_from_api_values_with_numbers_and_serial_dates():
    values = [
        ["Date", "Particulars", "Vch No.", "Debit", "Credit"],
        [45748, "Rent", "PAY-1", 10000.5, ""],
        [45748, "Bank", "PAY-1", "", 10000.5],
    ]
    result = parse_rows(values, "Journal")
    assert result.sheet_name == "Journal"
    assert [(r.account_ref, r.debit, r.credit, r.transaction_date) for r in result.rows] == [
        ("Rent", Decimal("10000.5"), Decimal("0"), date(2025, 4, 1)),
        ("Bank", Decimal("0"), Decimal("10000.5"), date(2025, 4, 1)),
    ]
    assert not result.issues


def test_header_below_title_rows_and_short_trailing_rows_and_row_numbers():
    values = [
        ["Acme Traders"],
        ["Journal FY 2025-26"],
        ["Date", "Account", "Debit", "Credit"],
        ["01-04-2025", "Rent", "1,000.00"],  # the API drops trailing empty cells
        ["01-04-2025", "Bank", None, "1,000.00"],
        [],
        [None, "  "],
    ]
    result = parse_rows(values, None)
    assert [r.row_number for r in result.rows] == [4, 5]
    assert result.total_debit == result.total_credit == Decimal("1000.00")


def test_csv_text_cells_use_the_normal_rules_including_indian_grouping():
    result = parse_rows([["Date", "Account", "Debit", "Credit"], ["15-04-2025", "Plant", "1,20,000.00", ""], ["15-04-2025", "Bank", "", "1,20,000.00"]], None)
    assert result.total_debit == Decimal("120000.00")


def test_bad_rows_are_flagged_not_dropped():
    result = parse_rows([["Date", "Account", "Debit", "Credit"], ["not a date", "Rent", "abc", ""]], None)
    assert len(result.rows) == 1
    assert {i.field for i in result.issues if i.severity.value == "ERROR"} >= {"date", "debit"}


def test_no_header_and_no_data_are_clear_errors():
    with pytest.raises(SheetsError) as a:
        parse_rows([["hello", "world"]], None)
    assert "header row" in str(a.value)
    with pytest.raises(SheetsError) as b:
        parse_rows([["Date", "Account", "Debit", "Credit"]], None)
    assert "no data rows" in str(b.value)


# ---- a mock Google --------------------------------------------------------------------------------------------------

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PEM = _KEY.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
SA_EMAIL = "milaan-reader@demo-project.iam.gserviceaccount.com"

VALUES = [
    ["Date", "Particulars", "Vch No.", "Debit", "Credit"],
    [45748, "Office Rent", "PAY-1", 10000, ""],
    [45748, "HDFC Bank", "PAY-1", "", 10000],
]
CSV_TEXT = "Date,Particulars,Vch No.,Debit,Credit\n01-04-2025,Office Rent,PAY-1,\"10,000.00\",\n01-04-2025,HDFC Bank,PAY-1,,\"10,000.00\"\n"


class MockGoogle(BaseHTTPRequestHandler):
    log: list = []
    claims: dict = {}
    jwt_ok = False

    def _send(self, status, body, ctype="application/json"):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):  # noqa: N802
        if self.path != "/token":
            return self._send(404, "{}")
        form = urllib.parse.parse_qs(self.rfile.read(int(self.headers["Content-Length"])).decode())
        assertion = form["assertion"][0]
        head, claims, sig = assertion.split(".")
        pad = lambda s: s + "=" * (-len(s) % 4)  # noqa: E731
        try:
            _KEY.public_key().verify(base64.urlsafe_b64decode(pad(sig)), f"{head}.{claims}".encode(), padding.PKCS1v15(), hashes.SHA256())
            MockGoogle.jwt_ok = True
        except Exception:  # noqa: BLE001
            MockGoogle.jwt_ok = False
            return self._send(400, json.dumps({"error": "invalid_grant", "error_description": "bad signature"}))
        MockGoogle.claims = json.loads(base64.urlsafe_b64decode(pad(claims)))
        MockGoogle.claims["_grant_type"] = form["grant_type"][0]
        self._send(200, json.dumps({"access_token": "tok123", "expires_in": 3600}))

    def do_GET(self):  # noqa: N802
        MockGoogle.log.append(self.path)
        url = urllib.parse.urlparse(self.path)
        parts = url.path.split("/")
        if url.path.startswith("/spreadsheets/d/") and url.path.endswith("/export"):
            sheet = parts[3]
            if sheet == PRIVATE_ID:
                return self._send(200, "<html>Sign in</html>", "text/html")
            if sheet == MISSING_ID:
                return self._send(404, "nope", "text/plain")
            return self._send(200, "﻿" + CSV_TEXT, "text/csv")
        if url.path.startswith("/v4/spreadsheets/"):
            if self.headers.get("Authorization") != "Bearer tok123":
                return self._send(401, json.dumps({"error": {"message": "no token"}}))
            sheet = parts[3]
            if sheet == NOSHARE_ID:
                return self._send(403, json.dumps({"error": {"message": "The caller does not have permission"}}))
            if sheet == MISSING_ID:
                return self._send(404, json.dumps({"error": {"message": "Requested entity was not found."}}))
            if len(parts) == 4:
                return self._send(200, json.dumps({"properties": {"title": "Acme books"}, "sheets": [
                    {"properties": {"sheetId": 0, "title": "Summary"}},
                    {"properties": {"sheetId": 777, "title": "Journal 'FY26'"}},
                ]}))
            return self._send(200, json.dumps({"range": "x", "majorDimension": "ROWS", "values": VALUES}))
        self._send(404, "{}")

    def log_message(self, *args):
        pass


@pytest.fixture()
def google(monkeypatch, tmp_path):
    server = HTTPServer(("127.0.0.1", 0), MockGoogle)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
    MockGoogle.log, MockGoogle.claims, MockGoogle.jwt_ok = [], {}, False
    key_file = tmp_path / "key.json"
    key_file.write_text(json.dumps({"client_email": SA_EMAIL, "private_key": _PEM, "token_uri": "https://oauth2.googleapis.com/token"}))
    monkeypatch.setenv("GOOGLE_SHEETS_API_BASE", base)
    monkeypatch.setenv("GOOGLE_SHEETS_EXPORT_BASE", base)
    monkeypatch.setenv("GOOGLE_TOKEN_URL", base + "/token")
    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_FILE", raising=False)
    yield {"base": base, "key_file": str(key_file), "monkeypatch": monkeypatch}
    server.shutdown()


def use_service_account(google):
    google["monkeypatch"].setenv("GOOGLE_SERVICE_ACCOUNT_FILE", google["key_file"])


# ---- service account ------------------------------------------------------------------------------------------------

def test_signed_token_is_accepted_by_google_and_carries_the_right_claims(google):
    use_service_account(google)
    account = client.load_service_account()
    assert client.access_token(account) == "tok123"
    assert MockGoogle.jwt_ok
    c = MockGoogle.claims
    assert c["iss"] == SA_EMAIL and c["scope"] == client.SCOPE and c["aud"] == account.token_uri
    assert c["exp"] - c["iat"] == 3600 and c["_grant_type"] == "urn:ietf:params:oauth:grant-type:jwt-bearer"


def test_tabs_and_values_are_read_read_only_with_quoted_tab_names(google):
    use_service_account(google)
    account = client.load_service_account()
    ref = parse_sheet_reference(GOOD_ID)
    info = client.get_sheet_info(ref, account)
    assert info.title == "Acme books" and [(t.title, t.gid) for t in info.tabs] == [("Summary", 0), ("Journal 'FY26'", 777)]
    assert client.fetch_tab_values(ref, "Journal 'FY26'", account) == VALUES
    last = urllib.parse.unquote(MockGoogle.log[-1])
    assert "/values/'Journal ''FY26'''" in last
    assert "valueRenderOption=UNFORMATTED_VALUE" in last and "dateTimeRenderOption=SERIAL_NUMBER" in last


def test_not_shared_gives_the_email_to_share_with(google):
    use_service_account(google)
    with pytest.raises(SheetsError) as info:
        client.get_sheet_info(parse_sheet_reference(NOSHARE_ID), client.load_service_account())
    assert SA_EMAIL in str(info.value) and "not shared" in str(info.value)


def test_missing_sheet_is_a_clear_error(google):
    use_service_account(google)
    with pytest.raises(SheetsError) as info:
        client.get_sheet_info(parse_sheet_reference(MISSING_ID), client.load_service_account())
    assert "could not find" in str(info.value)


def test_a_wrong_key_is_rejected_by_google_with_a_helpful_message(google, tmp_path):
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = other.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"client_email": SA_EMAIL, "private_key": pem}))
    google["monkeypatch"].setenv("GOOGLE_SERVICE_ACCOUNT_FILE", str(bad))
    with pytest.raises(SheetsError) as info:
        client.access_token(client.load_service_account())
    assert "refused the service account sign-in" in str(info.value)


@pytest.mark.parametrize("content", ["not json", json.dumps({"client_email": "a@b"}), json.dumps({"client_email": "a@b", "private_key": "nope"})])
def test_broken_key_files_are_explained(google, tmp_path, content):
    path = tmp_path / "k.json"
    path.write_text(content)
    google["monkeypatch"].setenv("GOOGLE_SERVICE_ACCOUNT_FILE", str(path))
    with pytest.raises(SheetsError):
        client.load_service_account()


def test_missing_key_file_is_explained(google):
    google["monkeypatch"].setenv("GOOGLE_SERVICE_ACCOUNT_FILE", "/no/such/file.json")
    with pytest.raises(SheetsError) as info:
        client.load_service_account()
    assert "does not exist" in str(info.value)


# ---- public link ----------------------------------------------------------------------------------------------------

def test_public_csv_is_read_including_a_byte_order_mark(google):
    rows = client.fetch_public_csv_rows(parse_sheet_reference(f"https://docs.google.com/spreadsheets/d/{GOOD_ID}/edit#gid=5"))
    assert rows[0] == ["Date", "Particulars", "Vch No.", "Debit", "Credit"]
    assert "gid=5" in MockGoogle.log[-1]
    assert parse_rows(rows, None).total_debit == Decimal("10000.00")


def test_private_sheet_in_public_mode_says_how_to_fix_it(google):
    with pytest.raises(SheetsError) as info:
        client.fetch_public_csv_rows(parse_sheet_reference(PRIVATE_ID))
    assert "private" in str(info.value) and "Anyone with the link" in str(info.value)


def test_missing_public_sheet(google):
    with pytest.raises(SheetsError) as info:
        client.fetch_public_csv_rows(parse_sheet_reference(MISSING_ID))
    assert "could not find" in str(info.value)


def test_unreachable_google_is_explained(monkeypatch):
    monkeypatch.setenv("GOOGLE_SHEETS_EXPORT_BASE", "http://127.0.0.1:1")
    with pytest.raises(SheetsError) as info:
        client.fetch_public_csv_rows(parse_sheet_reference(GOOD_ID))
    assert "cannot reach Google" in str(info.value)


# ---- the command line -----------------------------------------------------------------------------------------------

def run_cli(capsys, *args):
    code = cli_main(["x", *args])
    out = capsys.readouterr()
    return code, out.out, out.err


def test_status_reports_the_mode(google, capsys):
    code, out, _ = run_cli(capsys, "status")
    assert code == 0 and json.loads(out)["mode"] == "public_link"
    use_service_account(google)
    code, out, _ = run_cli(capsys, "status")
    data = json.loads(out)
    assert code == 0 and data["mode"] == "service_account" and data["service_account_email"] == SA_EMAIL


def test_status_never_fails_on_a_broken_key_file(google, capsys):
    google["monkeypatch"].setenv("GOOGLE_SERVICE_ACCOUNT_FILE", "/no/such/file.json")
    code, out, _ = run_cli(capsys, "status")
    assert code == 0 and json.loads(out)["mode"] == "service_account_error"


def test_check_lists_tabs_and_suggests_the_linked_one(google, capsys):
    use_service_account(google)
    code, out, _ = run_cli(capsys, "check", f"https://docs.google.com/spreadsheets/d/{GOOD_ID}/edit#gid=777")
    data = json.loads(out)
    assert code == 0 and data["title"] == "Acme books" and data["suggested_tab"] == "Journal 'FY26'" and len(data["tabs"]) == 2


def test_check_in_public_mode_proves_the_sheet_is_reachable(google, capsys):
    code, out, _ = run_cli(capsys, "check", GOOD_ID)
    data = json.loads(out)
    assert code == 0 and data["mode"] == "public_link" and data["rows_seen"] == 3


def test_cli_turns_user_fixable_problems_into_400(google, capsys):
    for args in (("check", "nonsense"), ("check", PRIVATE_ID)):
        code, _, err = run_cli(capsys, *args)
        assert code == 1 and json.loads(err)["status"] == 400
    use_service_account(google)
    code, _, err = run_cli(capsys, "import", GOOD_ID, "No such tab", "f", "c", "s")
    assert code == 1 and json.loads(err)["status"] == 400 and "no tab called" in json.loads(err)["error"]