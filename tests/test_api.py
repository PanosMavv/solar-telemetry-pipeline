"""HTTP-level tests: the API must never 500 on garbage input, must
return 503 when the DB is down, and must store valid records.
"""

from typing import Any

import pytest
import sqlite3
from sqlalchemy import func, select

from fastapi.testclient import TestClient

from app.api import create_fastapi
from app.models import SolarTelemetryRow
from app.pipeline import Pipeline

from tests.conftest import VALID_PAYLOAD


class TestApi:
    def test_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_valid_payload_accepted_202(self, client):
        resp = client.post("/ingest/telemetry", json=VALID_PAYLOAD)
        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "accepted"
        assert body["panel_id"] == "SP-1001"
        assert "db_id" in body

    def test_valid_payload_stored_with_derived_fields(self, client, engine):
        client.post("/ingest/telemetry", json=VALID_PAYLOAD)
        with engine.connect() as conn:
            rows = conn.execute(select(SolarTelemetryRow)).all()
        assert len(rows) == 1
        assert rows[0].power_w == pytest.approx(12.5 * 4.2)
        assert rows[0].efficiency == pytest.approx(52.5 / (850.0 * 1.6) * 100)
        assert rows[0].ingested_at is not None

    @pytest.mark.parametrize(
        "payload",
        [None, 42, "string", ["list"], {}, {"voltage_v": "N/A"}, {"temperature_c": None}],
    )
    def test_malformed_or_garbage_body_never_returns_500(self, client, payload: Any):
        resp = client.post("/ingest/telemetry", json=payload)
        assert resp.status_code != 500
        # non-object JSON -> 422 ; garbage object -> 200 discarded
        assert resp.status_code in (200, 202, 422)

    def test_malformed_json_returns_422(self, client):
        resp = client.post("/ingest/telemetry", content="definitely not json {{")
        assert resp.status_code == 422

    def test_empty_object_discarded_200(self, client):
        resp = client.post("/ingest/telemetry", json={})
        assert resp.status_code == 200
        assert resp.json()["status"] == "discarded"
        assert "reason" in resp.json()

    def test_db_failure_returns_503_not_500(self):
        def failing_factory():
            raise sqlite3.OperationalError("db down")

        app = create_fastapi(Pipeline(failing_factory))
        client = TestClient(app)
        resp = client.post("/ingest/telemetry", json=VALID_PAYLOAD)
        assert resp.status_code == 503

    def test_discarded_payload_not_persisted(self, client, engine):
        client.post("/ingest/telemetry", json={**VALID_PAYLOAD, "voltage_v": "N/A"})
        with engine.connect() as conn:
            count = conn.execute(select(func.count(SolarTelemetryRow.id))).scalar()
        assert count == 0
