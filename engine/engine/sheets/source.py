"""
Understands what a person pastes: a full Google Sheets link, or just the sheet's id.

Nothing here fetches anything. The engine only ever builds its own Google addresses from the validated id and tab
number, so a pasted link can never make the server call some other website.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import parse_qs, urlparse

SHEET_ID = re.compile(r"^[A-Za-z0-9_-]{15,120}$")
_PATH_ID = re.compile(r"^/spreadsheets/(?:u/\d+/)?d/([A-Za-z0-9_-]+)")
_GID = re.compile(r"(?:^|[#&?])gid=(\d{1,12})(?:$|&)")


class SheetsError(ValueError):
    """Bad input, or a sheet that cannot be read. A ValueError so the API reports it as a 400."""


@dataclass(frozen=True)
class SheetRef:
    sheet_id: str
    gid: Optional[int]  # the tab number from the link (#gid=123), if the link had one


def parse_sheet_reference(text: str) -> SheetRef:
    raw = (text or "").strip()
    if not raw:
        raise SheetsError("paste the Google Sheets link (or the sheet id)")
    if "/" not in raw and "." not in raw:
        if not SHEET_ID.match(raw):
            raise SheetsError("that does not look like a Google Sheets id")
        return SheetRef(raw, None)

    url = urlparse(raw if "://" in raw else "https://" + raw)
    if url.scheme not in ("http", "https") or (url.hostname or "").lower() != "docs.google.com":
        raise SheetsError("that is not a Google Sheets link (it should start with https://docs.google.com/spreadsheets/d/...)")
    match = _PATH_ID.match(url.path)
    if not match or not SHEET_ID.match(match.group(1)):
        raise SheetsError("could not find the sheet id in that link")

    gid_text = (parse_qs(url.query).get("gid") or [None])[0]
    if gid_text is None:
        found = _GID.search("#" + url.fragment) if url.fragment else None
        gid_text = found.group(1) if found else None
    gid = int(gid_text) if gid_text and gid_text.isdigit() else None
    return SheetRef(match.group(1), gid)
