"""Strict Pydantic validation schema for raw solar panel telemetry.

Raw payloads arrive from untrusted sensor firmware. This schema guarantees:

* numeric fields are real numbers — strings ("30.0", "N/A"), booleans and
  `null` are rejected (``Field(strict=True)``);
* ``panel_id`` must be a non-empty string (int/float/null rejected);
* ``timestamp`` must be an ISO-8601 datetime;
* physically impossible readings (negative irradiance, negative voltage)
  are rejected via field constraints.

Validation failures raise ``pydantic.ValidationError`` and are caught by the
pipeline, which logs a warning and discards the record.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SolarTelemetry(BaseModel):
    """A single valid raw telemetry record.

    Raises ``ValidationError`` on garbage data (wrong types, nulls,
    missing keys, unparseable timestamps, negative irradiance, ...).
    """

    model_config = ConfigDict(
        # Unknown fields (firmware upgrades) are ignored rather than rejected,
        # which keeps the pipeline resilient to evolving sensor firmware.
        extra="ignore",
    )

    panel_id: str = Field(
        strict=True,
        min_length=1,
        max_length=64,
        description="Unique solar panel identifier, e.g. 'SP-1001'.",
    )
    timestamp: datetime = Field(
        description="ISO-8601 timestamp, e.g. '2026-11-16T10:00:00Z'.",
    )
    voltage_v: float = Field(
        strict=True,
        gt=0,
        description="Panel voltage in volts. Must be a real number > 0.",
    )
    current_a: float = Field(
        strict=True,
        ge=0,
        description="Panel current in amperes. Must be a real number >= 0.",
    )
    temperature_c: float = Field(
        strict=True,
        gt=-273.15,
        description="Cell temperature in degrees Celsius. Must be above absolute zero.",
    )
    irradiance_w_m2: float = Field(
        strict=True,
        ge=0,
        description="Solar irradiance in W/m2. Must be a real number >= 0; negative readings are invalid.",
    )
