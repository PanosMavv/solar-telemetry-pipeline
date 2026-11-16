"""Shared test fixtures: in-memory/ephemeral SQLite DB, pipeline, FastAPI client."""

import pytest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api import create_fastapi
from app.models import Base
from app.pipeline import Pipeline

VALID_PAYLOAD = {
    "panel_id": "SP-1001",
    "timestamp": "2026-11-16T10:00:00Z",
    "voltage_v": 12.5,
    "current_a": 4.2,
    "temperature_c": 35.1,
    "irradiance_w_m2": 850.0,
}


@pytest.fixture
def engine(tmp_path):
    db_path = tmp_path / "test.db"
    engine_ = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine_)
    return engine_


@pytest.fixture
def session_factory(engine):
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture
def pipeline(session_factory):
    return Pipeline(session_factory)


@pytest.fixture
def app(pipeline):
    return create_fastapi(pipeline)


@pytest.fixture
def client(app):
    return TestClient(app)
