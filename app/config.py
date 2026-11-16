"""Application settings.

All settings can be overridden via `SOLAR_`-prefixed environment variables
or a `.env` file in the project root (see `.env.example`).
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for the solar telemetry pipeline."""

    model_config = SettingsConfigDict(
        env_prefix="SOLAR_",
        env_file=".env",
        extra="ignore",
    )

    # --- Storage -----------------------------------------------------------
    # SQLite URL (relative to the working directory unless absolute).
    db_url: str = "sqlite:///./data/solar.db"
    db_echo: bool = False  # echo SQLAlchemy SQL statements (debugging only)

    # --- Logging -----------------------------------------------------------
    log_file: str = "solar_pipeline.log"

    # --- API / built-in simulator ------------------------------------------
    port: int = 8000
    simulator_interval: float = 5.0
    garbage_every_n: int = 12
