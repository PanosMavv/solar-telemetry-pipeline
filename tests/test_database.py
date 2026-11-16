"""tenacity retry behavior in the database layer.

Covers the "retry 3 times with exponential backoff before failing" requirement.
"""

import sqlite3
from dataclasses import asdict

import pytest
from tenacity import RetryCallState

import sqlalchemy.exc

from app import database
from app.processor import process
from app.schemas import SolarTelemetry

from tests.conftest import VALID_PAYLOAD


def _payload() -> dict:
    return asdict(process(SolarTelemetry(**VALID_PAYLOAD)))


class TestPersistWithRetry:
    def test_gives_up_after_3_attempts(self):
        """A connection that always drops must fail after exactly 3 attempts."""
        calls: list[None] = []

        def failing_factory():
            calls.append(None)
            raise sqlite3.OperationalError("connection dropped")

        with pytest.raises(sqlite3.OperationalError):
            database.persist_with_retry(failing_factory, _payload())
        assert len(calls) == database.DB_RETRY_ATTEMPTS == 3

    def test_succeeds_after_two_failures(self, session_factory):
        """The third attempt must succeed when the DB recovers."""
        calls: list[None] = []

        def flaky_factory():
            calls.append(None)
            if len(calls) < 3:
                raise sqlite3.OperationalError("connection dropped")
            return session_factory()

        db_id = database.persist_with_retry(flaky_factory, _payload())
        assert db_id is not None
        assert len(calls) == 3

    def test_success_no_retries_on_first_attempt(self, session_factory):
        calls: list[None] = []

        def healthy_factory():
            calls.append(None)
            return session_factory()

        database.persist_with_retry(healthy_factory, _payload())
        assert len(calls) == 1

    def test_backoff_schedule_is_exponential(self):
        """Each retry waits twice as long as the previous one.

        The wait strategy reads ``retry_state.attempt_number`` and computes
        ``multiplier * base**(attempt_number - 1)`` clamped to [min, max].
        With the configured constants (multiplier=0.25, base=2, min=0.1,
        max=4.0) the schedule is 0.25 s, 0.5 s, 1.0 s.
        """
        state = RetryCallState(retry_object=object(), fn=lambda: 1, args=(), kwargs={})
        sleeps = []
        for attempt in range(1, 4):
            state.attempt_number = attempt
            sleeps.append(database.DB_BACKOFF_WAIT(state))

        assert [round(s, 4) for s in sleeps] == [0.25, 0.5, 1.0]
        for a, b in zip(sleeps, sleeps[1:]):
            assert b == pytest.approx(a * 2)
        assert all(s >= database.BACKOFF_MIN for s in sleeps)
        assert all(s <= database.BACKOFF_MAX for s in sleeps)

    def test_retry_logs_warning_before_sleeping(self, caplog):
        caplog.set_level("WARNING")
        calls: list[None] = []

        def failing_factory():
            calls.append(None)
            raise sqlite3.OperationalError("connection dropped")

        with pytest.raises(sqlite3.OperationalError):
            database.persist_with_retry(failing_factory, _payload())
        assert "Retrying" in caplog.text
        # The two backoff sleeps (0.25 s, 0.5 s) are logged with their values.
        assert "0.25" in caplog.text
        assert "0.5" in caplog.text

    def test_retries_sqlalchemy_errors_too(self, session_factory):
        """A wrapped SQLAlchemy error (as raised on a real DB failure) is retried too."""
        def failing_factory():
            raise sqlalchemy.exc.OperationalError(
                None, None, sqlite3.OperationalError("db down")
            )

        with pytest.raises(sqlalchemy.exc.OperationalError):
            database.persist_with_retry(failing_factory, _payload())
