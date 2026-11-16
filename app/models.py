"""SQLAlchemy ORM models. The only table the pipeline writes to is
``solar_telemetry``.
"""

from datetime import datetime

from sqlalchemy import DateTime, Float, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class SolarTelemetryRow(Base):
    """A row of the ``solar_telemetry`` table."""

    __tablename__ = "solar_telemetry"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # --- raw sensor values --------------------------------------------------
    panel_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    voltage_v: Mapped[float] = mapped_column(Float, nullable=False)
    current_a: Mapped[float] = mapped_column(Float, nullable=False)
    temperature_c: Mapped[float] = mapped_column(Float, nullable=False)
    irradiance_w_m2: Mapped[float] = mapped_column(Float, nullable=False)

    # --- derived fields, computed at ingestion time -------------------------
    power_w: Mapped[float] = mapped_column(Float, nullable=False)
    efficiency: Mapped[float] = mapped_column(Float, nullable=False)

    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
