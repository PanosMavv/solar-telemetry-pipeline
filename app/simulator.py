"""Simulates a solar panel sending telemetry every N seconds.

Generates a JSON record every ``interval`` seconds (default: 5 s) and POSTs
it to the ingestion endpoint. Every Nth record is intentionally invalid with
a rotating garbage pattern (string floats, null values, missing keys, negative
irradiance, unparseable timestamps) to prove that the pipeline discards bad
data gracefully.

Usage:
    python -m app.simulator                          # -> http://127.0.0.1:8000, one reading / 5 s
    python -m app.simulator --base-url http://api:8000 --cycles 100
"""

import argparse
import logging
import random
import time
from datetime import datetime, timezone

import httpx

from app.config import Settings
from app.logging_setup import setup_logging

logger = logging.getLogger("solar")

PANEL_IDS = ("SP-1001", "SP-1002", "SP-1003", "SP-1004")


def _now_utc_iso() -> str:
    """ISO-8601 UTC timestamp with 'Z' suffix, as a real sensor would send it."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _valid_record(index: int) -> dict:
    return {
        "panel_id": PANEL_IDS[index % len(PANEL_IDS)],
        "timestamp": _now_utc_iso(),
        "voltage_v": round(random.uniform(29.0, 31.0), 2),
        "current_a": round(random.uniform(6.0, 7.5), 2),
        "temperature_c": round(random.uniform(20.0, 45.0), 1),
        "irradiance_w_m2": round(random.uniform(400.0, 1000.0), 1),
    }


_GARBAGE_VARIANTS = [
    # 0: string instead of a float
    lambda base: {**base, "voltage_v": "THIRTY_POINT_ZERO"},
    # 1: null value
    lambda base: {**base, "temperature_c": None},
    # 2: missing required key
    lambda base: {k: v for k, v in base.items() if k != "irradiance_w_m2"},
    # 3: negative irradiance
    lambda base: {**base, "irradiance_w_m2": -50.0},
    # 4: unparseable timestamp
    lambda base: {**base, "timestamp": "not-a-valid-timestamp"},
]


def _garbage_record(index: int) -> dict:
    base = _valid_record(index)
    return _GARBAGE_VARIANTS[index % len(_GARBAGE_VARIANTS)](base)


def _wait_until_ready(client: httpx.Client, timeout: float = 15.0) -> bool:
    """Poll `/health` until the API responds, or the deadline is reached."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            resp = client.get("/health", timeout=timeout)
            if resp.status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    return False


def run(
    base_url: str,
    interval: float = 5.0,
    cycles: int = 0,
    garbage_every_n: int = 12,
    timeout: float = 3.0,
) -> None:
    """Run the simulator loop. ``cycles=0`` means infinite."""
    setup_logging(Settings().log_file)

    client = httpx.Client(base_url=base_url, timeout=timeout)
    try:
        if not _wait_until_ready(client, timeout=15.0):
            logger.warning(
                "API not ready after %ds; continuing (failed sends will retry next cycle)",
                15.0,
            )
        logger.info(
            "Telemetry simulator started: one reading every %.1f s -> %s (garbage every %d)",
            interval,
            base_url,
            garbage_every_n,
        )
        sent = 0
        while True:
            if cycles and sent >= cycles:
                break
            is_garbage = sent % garbage_every_n == 0
            record = _garbage_record(sent) if is_garbage else _valid_record(sent)
            try:
                resp = client.post(f"/ingest/telemetry", json=record)
                try:
                    body = resp.json()
                except httpx.JSONDecodeError:
                    body = {"status": resp.text}
                logger.info(
                    "Cycle %d: HTTP %d -> %s",
                    sent,
                    resp.status_code,
                    body.get("status", body),
                )
                if resp.status_code >= 500:
                    logger.error("Server error for cycle %d (HTTP %d)", sent, resp.status_code)
            except httpx.HTTPError as exc:
                logger.warning(
                    "Cycle %d: could not reach %s (%s) - retrying next cycle",
                    sent,
                    base_url,
                    exc,
                )
            sent += 1
            if cycles and sent >= cycles:
                break
            time.sleep(interval)
    finally:
        client.close()
    logger.info("Telemetry simulator finished (%d readings sent)", sent)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Solar telemetry simulator")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--interval", type=float, default=5.0, help="seconds between readings")
    parser.add_argument("--cycles", type=int, default=0, help="number of readings to send (0 = infinite)")
    parser.add_argument("--garbage-every", type=int, default=12, help="inject garbage every Nth reading")
    parser.add_argument("--timeout", type=float, default=3.0)
    args = parser.parse_args(argv)
    run(
        base_url=args.base_url,
        interval=args.interval,
        cycles=args.cycles,
        garbage_every_n=args.garbage_every,
        timeout=args.timeout,
    )


if __name__ == "__main__":
    main()
