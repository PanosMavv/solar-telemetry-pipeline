"""Pydantic schema validation: valid records + garbage data."""

from datetime import datetime

import pytest
from pydantic import ValidationError

from app.schemas import SolarTelemetry

from tests.conftest import VALID_PAYLOAD


@pytest.mark.parametrize(
    "payload",
    [
        {},  # all keys missing
        {**VALID_PAYLOAD, "irradiance_w_m2": -50.0},  # negative irradiance
        {**VALID_PAYLOAD, "voltage_v": "30.0"},  # string instead of a float
        {**VALID_PAYLOAD, "voltage_v": "THIRTY"},  # string instead of a float
        {**VALID_PAYLOAD, "voltage_v": True},  # boolean is not a number here
        {**VALID_PAYLOAD, "current_a": "4.2"},  # string instead of a float
        {**VALID_PAYLOAD, "temperature_c": None},  # null value
        {**VALID_PAYLOAD, "irradiance_w_m2": None},  # null value
        {**VALID_PAYLOAD, "panel_id": 1001},  # int panel id
        {**VALID_PAYLOAD, "panel_id": ""},  # empty panel id
        {**VALID_PAYLOAD, "panel_id": None},  # null panel id
        {**VALID_PAYLOAD, "voltage_v": -5.0},  # negative voltage
        {**VALID_PAYLOAD, "timestamp": "not-a-date"},  # unparseable timestamp
        {**VALID_PAYLOAD, "timestamp": "2026-13-45T10:00:00Z"},  # impossible date
        {**VALID_PAYLOAD, "timestamp": None},  # null timestamp
    ],
)
def test_garbage_record_is_rejected(payload):
    with pytest.raises(ValidationError):
        SolarTelemetry(**payload)


def test_valid_record_validates():
    rec = SolarTelemetry(**VALID_PAYLOAD)
    assert rec.panel_id == "SP-1001"
    assert rec.voltage_v == 12.5
    assert rec.current_a == 4.2
    assert isinstance(rec.timestamp, datetime)
    assert rec.timestamp.tzinfo is not None


def test_int_values_for_float_fields_are_accepted():
    rec = SolarTelemetry(**{**VALID_PAYLOAD, "voltage_v": 13, "irradiance_w_m2": 900})
    assert rec.voltage_v == 13.0
    assert rec.irradiance_w_m2 == 900.0


def test_extra_fields_are_ignored():
    rec = SolarTelemetry(**{**VALID_PAYLOAD, "firmware": "2.1", "extra": "x"})
    assert rec.voltage_v == 12.5


def test_naive_timestamp_is_accepted():
    rec = SolarTelemetry(**{**VALID_PAYLOAD, "timestamp": "2026-11-16T10:00:00"})
    assert rec.timestamp == datetime(2026, 11, 16, 10, 0, 0)


def test_aware_timestamp_with_offset_is_accepted():
    rec = SolarTelemetry(**{**VALID_PAYLOAD, "timestamp": "2026-11-16T12:30:00+02:00"})
    assert rec.timestamp.hour == 12
    assert rec.timestamp.tzinfo is not None


def test_zero_irradiance_is_accepted():
    rec = SolarTelemetry(**{**VALID_PAYLOAD, "irradiance_w_m2": 0.0})
    assert rec.irradiance_w_m2 == 0.0
