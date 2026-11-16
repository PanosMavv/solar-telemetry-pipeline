"""SQLite persistence with tenacity-based retry for dropped connections.

If a DB operation fails (connection dropped, lock, ...), the whole persist
operation is retried up to ``DB_RETRY_ATTEMPTS`` (3) times, each with a FRESH
session and an exponentially growing backoff (0.25s -> 0.5s -> 1.0s, ...).
If all attempts fail, the original SQLAlchemy / sqlite3 error is re-raised
and the API responds with 503.
"""

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from tenacity import before_sleep_log, retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.models import SolarTelemetryRow

logger = logging.getLogger("solar")

# --- Retry policy ----------------------------------------------------------
DB_RETRY_ATTEMPTS = 3
BACKOFF_MULTIPLIER = 0.25
BACKOFF_MIN = 0.1
BACKOFF_MAX = 4.0

DB_BACKOFF_WAIT = wait_exponential(
    multiplier=BACKOFF_MULTIPLIER,
    min=BACKOFF_MIN,
    max=BACKOFF_MAX,
)

DB_RETRIES = retry(
    stop=stop_after_attempt(DB_RETRY_ATTEMPTS),
    wait=DB_BACKOFF_WAIT,
    retry=retry_if_exception_type((SQLAlchemyError, sqlite3.Error)),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)

# --- Engine / session factory (module level, initialized by init_database) -
engine: Optional[Any] = None
SessionLocal: Optional[sessionmaker] = None


def _ensure_sqlite_directory(db_url: str) -> None:
    prefix = "sqlite:///"
    if not db_url.startswith(prefix):
        return
    path = Path(db_url[len(prefix):])
    path.parent.mkdir(parents=True, exist_ok=True)


def init_database(db_url: str, echo: bool = False) -> tuple[Any, "sessionmaker"]:
    """Create the engine + session factory and ensure the storage directory.

    Returns ``(engine, session_factory)``.
    """
    global engine, SessionLocal
    _ensure_sqlite_directory(db_url)
    kwargs: dict[str, Any] = {"echo": echo}
    if db_url.startswith("sqlite:"):
        # Uvicorn runs sync endpoints in a worker thread pool; a connection
        # created on one thread must not be used from another.
        kwargs["connect_args"] = {"check_same_thread": False}
    engine = create_engine(db_url, **kwargs)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    return engine, SessionLocal


def get_session_factory() -> "sessionmaker":
    if SessionLocal is None:
        raise RuntimeError("Database not initialized: call init_database() first.")
    return SessionLocal


def close_engine() -> None:
    global engine
    if engine is not None:
        engine.dispose()
        engine = None


@DB_RETRIES
def persist_with_retry(
    session_factory: Callable[[], Session],
    row: dict[str, Any],
) -> int:
    """Insert ``row`` into ``solar_telemetry`` and return the new row id.

    ``row`` is a plain dict (e.g. ``dataclasses.asdict(ProcessedTelemetry)``).
    Each attempt creates a FRESH session, so a dropped connection does not
    leak into the retry.
    """
    session: Optional[Session] = None
    try:
        session = session_factory()
        db_row = SolarTelemetryRow(**row)
        # Server receipt time, UTC-naive, to match the stored `timestamp`.
        db_row.ingested_at = datetime.now(timezone.utc).replace(tzinfo=None)
        session.add(db_row)
        session.commit()
        return db_row.id
    finally:
        if session is not None:
            try:
                session.close()
            except Exception:
                # A failing close must never mask the original result.
                logger.debug("Failed to close session", exc_info=True)
