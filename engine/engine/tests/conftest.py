"""
Shared test setup.

The file importers' command lines (ledger files, bank statements, registers, Google Sheets, Tally) read the company's
date rules from its accounting policy, which needs a database. The unit tests have none, so by default they use the
legacy rules (a company with no policy). A test that wants a company's rules sets them with `use_rules(...)` or replaces
`company_date_rules` itself.
"""
from contextlib import contextmanager

import pytest

from engine.calendars.dates import LEGACY_RULES, use_rules


@contextmanager
def _no_database_rules(firm_id, company_id):
    with use_rules(LEGACY_RULES):
        yield LEGACY_RULES


@pytest.fixture(autouse=True)
def _importers_use_legacy_date_rules_without_a_database(monkeypatch):
    import importlib
    for name in ("ingestion", "bank", "registers", "sheets", "tally"):
        module = importlib.import_module(f"engine.{name}.cli")
        monkeypatch.setattr(module, "company_date_rules", _no_database_rules)