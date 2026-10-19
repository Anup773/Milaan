"""
Talks to a running Tally over its built-in HTTP interface (Tally must be open with a company loaded and
"Enable ODBC / allow XML over HTTP" switched on, usually on port 9000).

The address is NEVER taken from a request. It comes from the TALLY_URL setting on the machine running the engine
(default http://localhost:9000), so nobody can point this at some other server through the API.
"""
from __future__ import annotations

import os
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date
from typing import List, Optional
from xml.sax.saxutils import escape

from .parser import TallyError, clean_xml_text, decode_xml_bytes

DEFAULT_URL = "http://localhost:9000"
TIMEOUT_SECONDS = 120
MAX_RESPONSE_BYTES = 200 * 1024 * 1024


def tally_url() -> str:
    url = (os.environ.get("TALLY_URL") or DEFAULT_URL).strip()
    if not url.lower().startswith(("http://", "https://")):
        raise TallyError(f"TALLY_URL must start with http:// or https:// (it is {url!r})")
    return url


def _post(xml_request: str) -> bytes:
    url = tally_url()
    request = urllib.request.Request(
        url,
        data=xml_request.encode("utf-8"),
        headers={"Content-Type": "text/xml; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise TallyError(f"Tally answered with HTTP {exc.code} at {url}") from exc
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        raise TallyError(
            f"cannot reach Tally at {url} ({reason}). Open Tally, load the company, and switch on its server "
            "(in TallyPrime: F1 Help > Settings > Connectivity, set it to act as Server or Both, port 9000), "
            "or upload an XML export instead"
        ) from exc
    if len(body) > MAX_RESPONSE_BYTES:
        raise TallyError("Tally's answer is too large. Fetch a shorter date range")
    return body


def _envelope(report_id: str, kind: str, variables: str) -> str:
    return (
        "<ENVELOPE><HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST>"
        f"<TYPE>{kind}</TYPE><ID>{escape(report_id)}</ID></HEADER>"
        f"<BODY><DESC><STATICVARIABLES><SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>{variables}"
        "</STATICVARIABLES></DESC></BODY></ENVELOPE>"
    )


def list_companies() -> List[str]:
    """Names of the companies currently open in Tally."""
    body = _post(_envelope("List of Companies", "Collection", ""))
    text = clean_xml_text(decode_xml_bytes(body))
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise TallyError(f"Tally's answer was not readable XML: {exc}") from exc
    names: List[str] = []
    for company in root.iter("COMPANY"):
        name = (company.get("NAME") or "").strip()
        if not name:
            child = company.find("NAME")
            name = (child.text or "").strip() if child is not None else ""
        if name and name not in names:
            names.append(name)
    return names


def fetch_day_book(from_date: date, to_date: date, company: Optional[str] = None) -> bytes:
    """The Day Book (every voucher) for a date range, as Tally's XML."""
    if to_date < from_date:
        raise TallyError("the end date is before the start date")
    variables = f"<SVFROMDATE>{from_date.strftime('%Y%m%d')}</SVFROMDATE><SVTODATE>{to_date.strftime('%Y%m%d')}</SVTODATE>"
    if company:
        variables += f"<SVCURRENTCOMPANY>{escape(company)}</SVCURRENTCOMPANY>"
    return _post(_envelope("Day Book", "Data", variables))