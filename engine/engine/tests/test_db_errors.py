"""Pure-logic tests for engine.db.errors -- no database."""
from engine.db.errors import error_payload, is_locked_period_error


class FakeDbError(Exception):
    def __init__(self, message, sqlstate):
        super().__init__(message)
        self.sqlstate = sqlstate


def test_locked_period_trigger_error_becomes_a_400_with_a_plain_message():
    exc = FakeDbError("accounting period abc is LOCKED; the journal cannot be changed", "23514")
    assert is_locked_period_error(exc)
    payload = error_payload(exc)
    assert payload["status"] == 400 and "LOCKED" in payload["error"]


def test_other_check_violations_are_not_mistaken_for_a_lock():
    exc = FakeDbError('new row violates check constraint "adjustments_check"', "23514")
    assert not is_locked_period_error(exc)
    assert error_payload(exc)["status"] == 500


def test_the_word_locked_alone_is_not_enough_without_the_right_sqlstate():
    assert error_payload(FakeDbError("LOCKED", "XX000"))["status"] == 500


def test_errors_without_a_sqlstate_stay_500():
    assert error_payload(RuntimeError("boom")) == {"error": "boom", "status": 500}