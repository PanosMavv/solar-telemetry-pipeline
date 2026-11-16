"""Derived-field computation (power, efficiency, UTC normalization)."""

from datetime import datetime, timezone

import pytest

from app.processor import PANEL_AREA_M2, process
from app.schemas import SolarTelemetry

from tests.conftest import VALID_PAYLOAD


def make_record(**overrides) -> SolarTelemetry:
    return SolarTelemetry(**{**VALID_PAYLOAD, **overrides})


def test_power_calculation():
    p = process(make_record())
    assert p.power_w == pytest.approx(12.5 * 4.2, abs=1e-5)


def test_efficiency_calculation():
    p = process(make_record())
    expected = (12.5 * 4.2) / (850.0 * PANEL_AREA_M2) * 100
    assert p.efficiency == pytest.approx(expected, abs=1e-5)


def test_efficiency_is_zero_for_zero_irradiance():
    p = process(make_record(irradiance_w_m2=0.0))
    assert p.efficiency == 0.0


def test_all_raw_fields_are_carried_over():
    p = process(make_record())
    assert p.panel_id == "SP-1001"
    assert p.voltage_v == 12.5
    assert p.current_a == 4.2
    assert p.temperature_c == 35.1
    assert p.irradiance_w_m2 == 850.0


def test_timestamp_is_normalized_to_utc():
    # 12:30+02:00 == 10:30 UTC
    p = process(make_record(timestamp="2026-11-16T12:30:00+02:00"))
    assert p.timestamp == datetime(2026, 11, 16, 10, 30, 0)


def test_naive_timestamp_is_assumed_utc():
    p = process(make_record(timestamp="2026-11-16T10:00:00"))
    assert p.timestamp == datetime(2026, 11, 16, 10, 0, 0)


def test_high_efficiency_case():
    # 30V * 7A = 210 W at 500 W/m2 over 1.6 m2 -> 26.25 %
    p = process(
        make_record(voltage_v=30.0, current_a=7.0, irradiance_w_m2=500.0)
    )
    assert p.efficiency == pytest.approx(210.0 / (500.0 * PANEL_AREA_M2) * 100)
