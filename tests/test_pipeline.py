"""End-to-end pipeline behavior: valid records get stored, garbage is
discarded without crashing.
"""

from typing import Any

import pytest
import sqlite3
from sqlalchemy import func, select

from app.models import SolarTelemetryRow
from app.pipeline import Pipeline, PipelineError
from app.schemas import SolarTelemetry

from tests.conftest import VALID_PAYLOAD

GARBAGE_PAYLOADS: list[Any] = [
    None,
    42,
    "garbage",
    [],
    {},
    {**VALID_PAYLOAD, "voltage_v": "N/A"},
    {**VALID_PAYLOAD, "temperature_c": None},
    {**VALID_PAYLOAD, "irradiance_w_m2": -50.0},
    {**VALID_PAYLOAD, "timestamp": "yesterday"},
    {"panel_id": None},
]


class TestIngest:
    def test_valid_payload_is_accepted_and_stored(self, pipeline, engine):
        result = pipeline.ingest(VALID_PAYLOAD)
        assert result.status == "accepted"
        assert result.db_id is not None
        assert result.record["panel_id"] == "SP-1001"

        with engine.connect() as conn:
            rows = conn.execute(
                select(SolarTelemetryRow).where(SolarTelemetryRow.panel_id == "SP-1001")
            ).all()
        assert len(rows) == 1
        assert rows[0].power_w == pytest.approx(52.5)
        assert rows[0].efficiency == pytest.approx(52.5 / (850.0 * 1.6) * 100)
        assert rows[0].id == result.db_id

    def test_valid_payload_derived_fields_in_result(self, pipeline):
        result = pipeline.ingest(VALID_PAYLOAD)
        assert result.record["power_w"] == pytest.approx(12.5 * 4.2)
        assert result.record["efficiency"] == pytest.approx(52.5 / (850.0 * 1.6) * 100)

    def test_garbage_payloads_are_discarded_never_raise(self, pipeline):
        for payload in GARBAGE_PAYLOADS:
            result = pipeline.ingest(payload)
            assert result.status == "discarded", f"expected discard for {payload!r}"
            assert result.db_id is None
            assert result.reason is not None

    def test_garbage_does_not_write_any_row(self, pipeline, engine):
        pipeline.ingest({**VALID_PAYLOAD, "voltage_v": "N/A"})
        pipeline.ingest(None)
        with engine.connect() as conn:
            count = conn.execute(select(func.count(SolarTelemetryRow.id))).scalar()
        assert count == 0

    def test_valid_stored_then_garbage_stays_stored(self, pipeline, engine):
        ok = pipeline.ingest(VALID_PAYLOAD)
        assert ok.status == "accepted"
        bad = pipeline.ingest({**VALID_PAYLOAD, "voltage_v": "N/A"})
        assert bad.status == "discarded"
        with engine.connect() as conn:
            count = conn.execute(select(func.count(SolarTelemetryRow.id))).scalar()
        assert count == 1

    def test_logs_warning_on_discard(self, pipeline, caplog):
        caplog.set_level("WARNING")
        pipeline.ingest({**VALID_PAYLOAD, "voltage_v": "N/A"})
        assert "Discarding invalid telemetry" in caplog.text

    def test_db_failure_raises_pipeline_error_after_retries(self):
        def failing_factory():
            raise sqlite3.OperationalError("connection dropped")

        pipeline = Pipeline(failing_factory)
        with pytest.raises(PipelineError):
            pipeline.ingest(VALID_PAYLOAD)
