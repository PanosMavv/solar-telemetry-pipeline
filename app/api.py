"""FastAPI service exposing the ingestion endpoints."""

import logging

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.pipeline import Pipeline, PipelineError

logger = logging.getLogger("solar")


def create_fastapi(pipeline: Pipeline) -> FastAPI:
    app = FastAPI(
        title="Solar Panel Telemetry Pipeline",
        version="1.0.0",
        description=(
            "Ingests raw solar panel telemetry JSON. "
            "202 = accepted and stored · 200 = discarded (invalid data) · "
            "422 = malformed JSON / non-object payload · 503 = DB unavailable."
        ),
    )

    @app.get("/health", tags=["meta"])
    def health_check() -> dict:
        """Liveness probe (used by the Docker healthcheck)."""
        return {"status": "ok"}

    @app.post("/ingest/telemetry", tags=["ingestion"])
    def ingest_telemetry(payload: dict) -> JSONResponse:
        """Accept a raw telemetry object.

        The payload is typed as ``dict`` on purpose so that garbage JSON
        objects (wrong types, nulls, missing keys) reach the strict Pydantic
        validation layer instead of FastAPI's default 422.
        """
        try:
            result = pipeline.ingest(payload)
        except PipelineError:
            # DB was unavailable for all retry attempts -> tell the caller
            # (sensor / MQTT client) to retry later.
            return JSONResponse(
                status_code=503,
                content={"status": "unavailable", "reason": "database unavailable"},
            )
        if result.status == "accepted":
            return JSONResponse(
                status_code=202,
                content={
                    "status": "accepted",
                    "panel_id": result.record["panel_id"],
                    "db_id": result.db_id,
                },
            )
        return JSONResponse(
            status_code=200,
            content={"status": "discarded", "reason": result.reason},
        )

    return app
