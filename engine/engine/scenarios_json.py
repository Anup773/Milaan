"""Tiny shared helper: a JSON-safe copy of a value (Decimals/dates become strings)."""
from __future__ import annotations

import json
from typing import Any


def plain(obj: Any) -> Any:
    return json.loads(json.dumps(obj, default=str))