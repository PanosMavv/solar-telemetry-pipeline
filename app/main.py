"""Application entry point.

Run the API:
    uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000
    python -m app.main

Run the API + built-in telemetry simulator (default: one reading / 5 s):
    python -m app.main --with-simulator
    python -m app.main --with-simulator --cycles 30 --interval 1

See README.md for details.
"""

import argparse
import threading

import uvicorn

from fastapi import FastAPI

from app import database
from app.api import create_fastapi
from app.config import Settings
from app.logging_setup import setup_logging
from app.models import Base
from app.pipeline import Pipeline
from app.simulator import run as run_simulator


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build a ready FastAPI app (initializes the DB and creates tables)."""
    settings = settings or Settings()
    setup_logging(settings.log_file)
    database.init_database(settings.db_url, echo=settings.db_echo)
    Base.metadata.create_all(database.engine)
    return create_fastapi(Pipeline(database.get_session_factory()))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Solar panel telemetry pipeline")
    parser.add_argument(
        "--with-simulator",
        action="store_true",
        help="start the built-in telemetry simulator (default: one reading / 5 s)",
    )
    parser.add_argument("--interval", type=float, default=5.0, help="seconds between simulated readings")
    parser.add_argument("--cycles", type=int, default=0, help="number of readings to send (0 = infinite)")
    parser.add_argument("--garbage-every", type=int, default=12, help="inject garbage every Nth reading")
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args(argv)

    settings = Settings()
    if args.port is not None:
        settings.port = args.port

    base_url = f"http://127.0.0.1:{settings.port}"
    if args.with_simulator:
        # The simulator waits for the API to be ready before its first
        # reading; it then runs in the background while uvicorn serves.
        thread = threading.Thread(
            target=run_simulator,
            kwargs={
                "base_url": base_url,
                "interval": args.interval,
                "cycles": args.cycles,
                "garbage_every_n": args.garbage_every,
            },
            daemon=True,
        )
        thread.start()

    uvicorn.run(create_app(settings), host="0.0.0.0", port=settings.port)


if __name__ == "__main__":
    main()
