"""Derived-field computation on validated telemetry.

The processor is pure (no I/O, no database), which keeps it trivially
unit-testable.
"""

from dataclasses import dataclass
from datetime import datetime, timezone

from app.schemas import SolarTelemetry

# Standard panel area in square meters, used for the efficiency formula.
PANEL_AREA_M2 = 1.6

# Rounding to avoid floating point noise in stored values.
ROUND_DIGITS = 6


@dataclass(frozen=True)
class ProcessedTelemetry:
    """Validated telemetry plus derived power and efficiency,
    ready to be persisted into ``solar_telemetry``."""

    panel_id: str
    timestamp: datetime
    voltage_v: float
    current_a: float
    temperature_c: float
    irradiance_w_m2: float
    power_w: float
    efficiency: float


def process(record: SolarTelemetry) -> ProcessedTelemetry:
    """Compute the derived fields.

    * ``power_w = voltage_v * current_a``
    * ``efficiency = power_w / (irradiance_w_m2 * PANEL_AREA_M2) * 100``
      (0.0 when irradiance is 0, i.e. night — avoids division by zero)

    Timestamps are normalized to UTC before being persisted
    (naive timestamps are assumed to be UTC).
    """
    power_w = round(record.voltage_v * record.current_a, ROUND_DIGITS)

    if record.irradiance_w_m2 > 0:
        efficiency = round(
            power_w / (record.irradiance_w_m2 * PANEL_AREA_M2) * 100,
            ROUND_DIGITS,
        )
    else:
        efficiency = 0.0

    ts = record.timestamp
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)  # assume UTC when sensor is naive
    ts = ts.astimezone(timezone.utc).replace(tzinfo=None)

    return ProcessedTelemetry(
        panel_id=record.panel_id,
        timestamp=ts,
        voltage_v=record.voltage_v,
        current_a=record.current_a,
        temperature_c=record.temperature_c,
        irradiance_w_m2=record.irradiance_w_m2,
        power_w=power_w,
        efficiency=efficiency,
    )
