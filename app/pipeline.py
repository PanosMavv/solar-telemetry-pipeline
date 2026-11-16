"""Ingestion core: validate -> enrich -> persist.

The pipeline is transport-agnostic: it receives a raw JSON-decoded object
(from FastAPI, paho-mqtt, a broker, ...) and returns an ``IngestResult``.

  * ``status == "accepted"``  -> record was stored in ``solar_telemetry``
  * ``status == "discarded"`` -> invalid input; no crash, warning logged
  * ``PipelineError``         -> a valid record could not be persisted after
                                 all retry attempts (DB problem -> HTTP 503)
"""

import logging
import sqlite3
from dataclasses import asdict, dataclass
from typing import Any, Callable, Literal, Optional

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app import database
from app.processor import process
from app.schemas import SolarTelemetry

logger = logging.getLogger("solar")


class PipelineError(RuntimeError):
    """Raised when a valid record could not be persisted after all retries."""


@dataclass(frozen=True)
class IngestResult:
    status: Literal["accepted", "discarded"]
    db_id: Optional[int] = None
    record: Optional[dict[str, Any]] = None
    reason: Optional[str] = None


class Pipeline:
    """Validates and persists solar telemetry records."""

    def __init__(self, session_factory: Callable[[], Session]):
        self._session_factory = session_factory

    @staticmethod
    def _format_validation_error(exc: ValidationError) -> str:
        return "; ".join(
            f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()
        )

    def ingest(self, raw: Any) -> IngestResult:
        """Accept a raw JSON object.

        Returns ``IngestResult`` with ``accepted`` (persisted) or
        ``discarded`` (invalid input, never raises for garbage data).
        Raises ``PipelineError`` only when a VALID record cannot be persisted
        after all DB retry attempts.
        """
        if not isinstance(raw, dict):
            logger.warning("Discarding non-object payload: %r", raw)
            return IngestResult(status="discarded", reason="payload must be a JSON object")

        try:
            record = SolarTelemetry(**raw)
        except ValidationError as exc:
            reason = self._format_validation_error(exc)
            logger.warning("Discarding invalid telemetry %r: %s", raw, reason)
            return IngestResult(status="discarded", reason=reason)

        row = process(record)
        payload = asdict(row)
        try:
            db_id = database.persist_with_retry(self._session_factory, payload)
        except (SQLAlchemyError, sqlite3.Error) as exc:
            logger.error(
                "Failed to persist panel %s after %d attempts: %s",
                row.panel_id,
                database.DB_RETRY_ATTEMPTS,
                exc,
            )
            raise PipelineError(f"Could not persist {row.panel_id}: {exc}") from exc

        return IngestResult(status="accepted", db_id=db_id, record=payload)
