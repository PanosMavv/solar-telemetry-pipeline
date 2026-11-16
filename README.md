# Solar Panel Telemetry Pipeline

A resilient Python data pipeline for an IoT solar-panel monitoring system. It receives
raw JSON telemetry from solar panels (simulated in-process, once every 5 seconds by
default), strictly validates it, computes derived fields (`power_w`, `efficiency`),
and persists the clean records to SQLite.

```
┌──────────────────┐       ┌────────────────────────────────────────────────────────┐
│  Solar panels    │──────►│  Ingestion (FastAPI  POST /ingest/telemetry)           │
│  (simulated 1/s  │       │                                                        │
│   or 5 s via     │──────►│  1. Pydantic strict validation                         │
│  HTTP simulator) │       │     • wrong types / nulls / missing keys  → discard    │
│                  │       │     • negative irradiance / unparseable ts  → discard  │
│                  │       │  2. Derived fields (processor)                         │
│                  │       │     • power_w      = voltage_v * current_a             │
│                  │       │     • efficiency   = power/(irradiance*area) * 100     │
│                  │       │  3. SQLite persistence (database)                      │
│                  │       │     • solar_telemetry table                            │
│                  │       │     • tenacity retry x3 + exponential backoff          │
└──────────────────┘       │       (dropped connection → fresh session each try)    │
                           └────────────────────────────────────────────────────────┘
```

## Project structure

```
solar-panel-pipeline/
├── app/
│   ├── __init__.py
│   ├── config.py          # pydantic-settings Settings (SOLAR_* env vars)
│   ├── schemas.py         # SolarTelemetry — strict Pydantic validation
│   ├── processor.py       # power_w / efficiency computation (pure function)
│   ├── models.py          # SQLAlchemy model for `solar_telemetry`
│   ├── database.py        # engine/session factory + tenacity retry
│   ├── pipeline.py        # ingest() — validate → process → persist
│   ├── api.py             # FastAPI app (POST /ingest/telemetry, GET /health)
│   ├── simulator.py       # telemetry simulator (default: one reading / 5 s)
│   ├── logging_setup.py   # console + rotating file (solar_pipeline.log)
│   └── main.py            # entry point: API, or API + built-in simulator
├── tests/
│   ├── conftest.py
│   ├── test_validation.py   # schema vs. valid + garbage inputs
│   ├── test_processor.py    # derived fields & UTC normalization
│   ├── test_pipeline.py     # accept / discard / never crash / retry → 503
│   ├── test_database.py     # 3 attempts, exponential backoff, recovery
│   └── test_api.py          # HTTP behavior (202 / 200 / 422 / 503)
├── data/                  # SQLite db + rotated logs (created at runtime)
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── .env.example
└── README.md
```

## Prerequisites

- Python 3.10+ (tested on 3.12; works on 3.11/3.13/3.15)
- Docker (optional, for containerized run)

## 1) Run the tests

```bash
# Windows (PowerShell)
py -3 -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\python -m pytest -v

# macOS / Linux
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m pytest -v
```

Expected result: all tests pass (`~35 tests`, e.g. `PASSED (36 tests, 0.9 s)`).
Each test uses a throwaway SQLite database in `tmp_path` — no file is left behind.

## 2) Run the application (local)

### API only

```bash
python -m app.main                                   # → http://127.0.0.1:8000
# or explicitly:
uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000
```

Open <http://127.0.0.1:8000/docs> for the interactive Swagger UI.

### API + telemetry simulator (one command demo)

```bash
python -m app.main --with-simulator                    # one reading / 5 s (default)
python -m app.main --with-simulator --cycles 30       # 30 readings, then keep running
python -m app.main --with-simulator --cycles 6 --garbage-every 2 --interval 1   # fast demo
```

### Stand-alone simulator (points at an already-running API)

```bash
python -m app.simulator --base-url http://localhost:8000
```

### Verify the data landed in the DB

```powershell
python - <<'PY'
import sqlite3
con = sqlite3.connect("data/solar.db")
rows = con.execute("""
    SELECT id, panel_id, timestamp, voltage_v, current_a,
           power_w, efficiency, ingested_at
    FROM solar_telemetry ORDER BY id
""").fetchall()
for r in rows:
    print(r)
PY
```

### Send a payload manually

```powershell
Invoke-RestMethod -Method POST -Uri http://127.0.0.1:8000/ingest/telemetry `
  -ContentType "application/json" `
  -Body '{"panel_id":"SP-1001","timestamp":"2026-11-16T10:00:00Z","voltage_v":12.5,"current_a":4.2,"temperature_c":35.1,"irradiance_w_m2":850}'
```

## 3) Run with Docker

```bash
docker compose up          # API on :8000 + simulator publishing every 5 s
docker compose logs -f api # watch logs (mirrors solar_pipeline.log)
```

`docker compose down -v` stops everything (the data volume is removed with `-v`).
The SQLite file lives on the `./data` volume so you can inspect it afterwards.

## How resilience works

| Failure mode | Behavior |
|---|---|
| String instead of float (`"voltage_v": "N/A"`) | Pydantic `ValidationError` → logged `WARNING` → record discarded, HTTP 200, no crash |
| Missing keys / null values / unparseable timestamp | Same: warning + discard (HTTP 200) |
| Negative irradiance / negative voltage | Field constraint (`ge`/`gt`) → warning + discard |
| Non-object JSON body (`[]`, `42`, bad JSON) | FastAPI rejects it → HTTP 422, no crash |
| Extra unknown fields | Ignored (`extra="ignore"` — firmware forward-compatibility) |
| DB connection drops / lock error | `tenacity`: up to **3 attempts** with exponential backoff (0.25 s → 0.5 s → 1.0 s, capped at 4 s), each attempt on a **fresh session**; then the error re-raises → API returns **503** (sensor can retry) |
| Zero irradiance (night) | `efficiency = 0.0` (division-by-zero-safe) |
| Naive timestamp | Assumed UTC, normalized before storage |
| Log growth | `RotatingFileHandler`: 5 × 5 MB → `solar_pipeline.log.1 … .5` |

### Response codes

| Code | Meaning |
|---|---|
| 202 | Accepted and stored in `solar_telemetry` |
| 200 | Discarded (invalid data) — body contains `reason` |
| 422 | Malformed JSON / non-object body |
| 503 | DB unavailable after all retry attempts |

## Configuration

All settings can be overridden via environment variables (copy `.env.example` → `.env`):

| Variable | Default | Description |
|---|---|---|
| `SOLAR_DB_URL` | `sqlite:///./data/solar.db` | SQLite URL (relative to the working dir) |
| `SOLAR_DB_ECHO` | `false` | Echo SQLAlchemy SQL statements |
| `SOLAR_LOG_FILE` | `solar_pipeline.log` | Rotating log file path |
| `SOLAR_PORT` | `8000` | API port |
| `SOLAR_SIMULATOR_INTERVAL` | `5.0` | Seconds between simulated readings |
| `SOLAR_GARBAGE_EVERY_N` | `12` | Inject a garbage record every Nth reading |

## Schema: `solar_telemetry`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | autoincrement |
| `panel_id` | TEXT(64) | indexed |
| `timestamp` | DATETIME | stored UTC (naive) |
| `voltage_v`, `current_a`, `temperature_c`, `irradiance_w_m2` | REAL | raw sensor values |
| `power_w` | REAL | `voltage_v * current_a` (computed at ingestion) |
| `efficiency` | REAL | `power_w / (irradiance_w_m2 * 1.6) * 100` |
| `ingested_at` | DATETIME | server receipt time |

## Extending to a real MQTT broker

The core (`pipeline.ingest`) is transport-agnostic. To use a real broker instead of the
simulator, replace the simulator loop with a `paho-mqtt` subscriber that calls the same
`Pipeline.ingest(payload)` on `on_message` — nothing else changes.
