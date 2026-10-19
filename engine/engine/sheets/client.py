"""
Reads a Google Sheet. Two ways, chosen by server settings (never by the request):

  1. Service account (private sheets). Set GOOGLE_SERVICE_ACCOUNT_FILE to the path of the service account's JSON key,
     then share each sheet with that account's email (Viewer is enough). The engine signs a short-lived token itself
     and calls the Sheets API read-only.
  2. Public link (no setup). Works for sheets shared as "Anyone with the link can view", through Google's CSV export.
     Only one tab is read: the one in the pasted link (#gid=...), or the first tab.

Only addresses built here from a validated sheet id are ever requested.
"""
from __future__ import annotations

import base64
import csv
import io
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .source import SheetRef, SheetsError

SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"
TIMEOUT_SECONDS = 60
MAX_BYTES = 50 * 1024 * 1024


def _api_base() -> str:
    return (os.environ.get("GOOGLE_SHEETS_API_BASE") or "https://sheets.googleapis.com").rstrip("/")


def _export_base() -> str:
    return (os.environ.get("GOOGLE_SHEETS_EXPORT_BASE") or "https://docs.google.com").rstrip("/")


@dataclass(frozen=True)
class ServiceAccount:
    email: str
    private_key: str
    token_uri: str


def load_service_account() -> Optional[ServiceAccount]:
    """The configured service account, or None when none is configured. Raises SheetsError if it is configured but unusable."""
    path = (os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE") or "").strip()
    if not path:
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            info = json.load(handle)
    except FileNotFoundError as exc:
        raise SheetsError(f"GOOGLE_SERVICE_ACCOUNT_FILE points to a file that does not exist: {path}") from exc
    except (OSError, ValueError) as exc:
        raise SheetsError(f"the service account key file could not be read as JSON: {exc}") from exc
    email, key = info.get("client_email"), info.get("private_key")
    if not isinstance(email, str) or not isinstance(key, str) or "PRIVATE KEY" not in key:
        raise SheetsError("the service account key file is missing client_email or private_key")
    token_uri = os.environ.get("GOOGLE_TOKEN_URL") or info.get("token_uri") or "https://oauth2.googleapis.com/token"
    if not str(token_uri).lower().startswith(("http://", "https://")):
        raise SheetsError("the service account token_uri is not a web address")
    return ServiceAccount(email=email, private_key=key, token_uri=str(token_uri))


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def build_signed_jwt(account: ServiceAccount, now: Optional[int] = None) -> str:
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
    except ImportError as exc:  # pragma: no cover - depends on the machine
        raise SheetsError("the 'cryptography' package is needed for a service account. Run: pip install cryptography") from exc
    issued = int(now if now is not None else time.time())
    header = {"alg": "RS256", "typ": "JWT"}
    claims = {"iss": account.email, "scope": SCOPE, "aud": account.token_uri, "iat": issued, "exp": issued + 3600}
    signing_input = f"{_b64(json.dumps(header, separators=(',', ':')).encode())}.{_b64(json.dumps(claims, separators=(',', ':')).encode())}"
    try:
        key = serialization.load_pem_private_key(account.private_key.encode("utf-8"), password=None)
        signature = key.sign(signing_input.encode("ascii"), padding.PKCS1v15(), hashes.SHA256())
    except Exception as exc:  # noqa: BLE001
        raise SheetsError(f"the service account private key could not be used: {exc}") from exc
    return f"{signing_input}.{_b64(signature)}"


def _read_limited(response: Any) -> bytes:
    body = response.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise SheetsError("the sheet is too large to import in one go")
    return body


def _http(request: urllib.request.Request) -> bytes:
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return _read_limited(response)
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            parsed = json.loads(exc.read(20000).decode("utf-8", errors="replace"))
            detail = (parsed.get("error") or {}).get("message") or parsed.get("error_description") or ""
        except Exception:  # noqa: BLE001
            pass
        raise _HttpFailure(exc.code, str(detail)) from exc
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
        raise SheetsError(f"cannot reach Google ({getattr(exc, 'reason', exc)}). Check this computer's internet connection") from exc


class _HttpFailure(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(f"HTTP {status}: {detail}")
        self.status = status
        self.detail = detail


def access_token(account: ServiceAccount) -> str:
    body = urllib.parse.urlencode(
        {"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": build_signed_jwt(account)}
    ).encode("ascii")
    request = urllib.request.Request(account.token_uri, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
    try:
        data = json.loads(_http(request).decode("utf-8"))
    except _HttpFailure as exc:
        raise SheetsError(f"Google refused the service account sign-in ({exc.detail or exc.status}). Check the key file is current") from exc
    except ValueError as exc:
        raise SheetsError("Google's sign-in answer was not understood") from exc
    token = data.get("access_token")
    if not isinstance(token, str) or not token:
        raise SheetsError("Google did not give an access token")
    return token


def _api_get(path: str, token: str, params: Optional[Dict[str, str]], account: ServiceAccount) -> Dict[str, Any]:
    url = _api_base() + path + ("?" + urllib.parse.urlencode(params) if params else "")
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    try:
        return json.loads(_http(request).decode("utf-8"))
    except _HttpFailure as exc:
        if exc.status in (401, 403):
            raise SheetsError(
                f"Google says this sheet is not shared with the service account. Share it (Viewer is enough) with {account.email}"
                + (f". Google said: {exc.detail}" if exc.detail else "")
            ) from exc
        if exc.status == 404:
            raise SheetsError("Google could not find that sheet. Check the link") from exc
        raise SheetsError(f"Google answered {exc.status}: {exc.detail or 'no details'}") from exc
    except ValueError as exc:
        raise SheetsError("Google's answer was not understood") from exc


@dataclass(frozen=True)
class Tab:
    title: str
    gid: int


@dataclass(frozen=True)
class SheetInfo:
    title: str
    tabs: List[Tab]


def get_sheet_info(ref: SheetRef, account: ServiceAccount) -> SheetInfo:
    token = access_token(account)
    data = _api_get(
        f"/v4/spreadsheets/{urllib.parse.quote(ref.sheet_id, safe='')}",
        token,
        {"fields": "properties.title,sheets.properties(sheetId,title)"},
        account,
    )
    tabs = [
        Tab(title=str(s["properties"]["title"]), gid=int(s["properties"]["sheetId"]))
        for s in data.get("sheets", [])
        if "properties" in s and "title" in s["properties"] and "sheetId" in s["properties"]
    ]
    if not tabs:
        raise SheetsError("that spreadsheet has no tabs")
    return SheetInfo(title=str((data.get("properties") or {}).get("title") or "Untitled"), tabs=tabs)


def fetch_tab_values(ref: SheetRef, tab_title: str, account: ServiceAccount) -> List[List[Any]]:
    token = access_token(account)
    quoted = "'" + tab_title.replace("'", "''") + "'"
    data = _api_get(
        f"/v4/spreadsheets/{urllib.parse.quote(ref.sheet_id, safe='')}/values/{urllib.parse.quote(quoted, safe='')}",
        token,
        {"majorDimension": "ROWS", "valueRenderOption": "UNFORMATTED_VALUE", "dateTimeRenderOption": "SERIAL_NUMBER"},
        account,
    )
    values = data.get("values") or []
    return [list(row) for row in values]


def fetch_public_csv_rows(ref: SheetRef) -> List[List[str]]:
    gid = ref.gid if ref.gid is not None else 0
    url = f"{_export_base()}/spreadsheets/d/{urllib.parse.quote(ref.sheet_id, safe='')}/export?format=csv&gid={gid}"
    request = urllib.request.Request(url, headers={"Accept": "text/csv"})
    try:
        body = _http(request)
    except _HttpFailure as exc:
        if exc.status in (401, 403):
            raise SheetsError(_NOT_PUBLIC) from exc
        if exc.status == 404:
            raise SheetsError("Google could not find that sheet or tab. Check the link (including the #gid=... part)") from exc
        raise SheetsError(f"Google answered {exc.status} when exporting the sheet") from exc
    text = body.decode("utf-8-sig", errors="replace")
    if text.lstrip()[:1] == "<":  # an HTML page: Google's sign-in screen for a private sheet
        raise SheetsError(_NOT_PUBLIC)
    return [row for row in csv.reader(io.StringIO(text, newline=""))]


_NOT_PUBLIC = (
    "this sheet is private. Either share it as 'Anyone with the link can view', or ask your administrator to set up "
    "a Google service account (then share the sheet with that account)"
)