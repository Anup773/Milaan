# Milaan — Phase 4: Excel/CSV Ingestion (Segment 1)

Drop-in for `engine/engine/ingestion/` and `engine/engine/tests/`. It doesn't
import anything from your existing `engine/ledger`, `engine/schedules`, etc.,
so it should merge in cleanly regardless of what else is in the repo —
tested that in isolation, see below.

## What this does
Raw Excel (`.xlsx`) or CSV → `ParseResult`: a list of normalized,
Decimal-safe rows plus a list of PASS/WARNING/ERROR-style issues (same
vocabulary as the reconciliation framework in ARCHITECTURE.md §7), so a bad
row is visible before Phase 5 (mapping) or persistence ever runs on it.

- **detect.py** — finds the header row (scans the first 10 rows; Tally/Excel
  exports often have a title/company-name row above the real header) and
  maps its columns to canonical fields (date, account, description, debit,
  credit, reference) via an alias table. Extend `ALIASES` for export formats
  it doesn't recognize yet.
- **money_parse.py** — text → Decimal/date. Handles Indian digit grouping
  ("1,20,000.00"), parenthesized negatives, and common date formats.
  Deliberately separate from `engine/ledger/money.py` — that module is
  normal-balance ledger arithmetic; this one is "never let a float near a
  rupee amount" on raw, messy spreadsheet text.
- **excel_parser.py / csv_parser.py** — format-specific readers that both
  funnel into `row_parser.build_row()`, so the field/validation logic lives
  in exactly one place instead of twice.
- **persist_stub.py** — DRAFT ONLY, not wired up anywhere. Column names are
  inferred from ARCHITECTURE.md §4, not checked against your real
  `0001_init_canonical_schema.sql`. Reconcile before using.

## What this doesn't do yet
- Write to Postgres for real (see persist_stub.py above)
- The Node API upload endpoint + BullMQ worker (`api/src/modules/imports/`)
- Phase 5 account mapping (raw `account_ref` → `accounts.id`)

## Install
Add to `engine/pyproject.toml` dependencies: `openpyxl>=3.1`
Then, from `engine/`: `pip install -e .` (or `uv sync` if you're on uv).

## Test
From `engine/`: `pytest engine/tests/test_ingestion.py -v`
6 tests, all passing against the included fixtures (verified in a sandbox
before sending this over — also spot-checked a title-row-above-header case
like a real Tally export, which isn't in the formal test file but parsed
correctly: 2/2 rows, no false errors).
