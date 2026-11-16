"""Console + rotating-file logging for the whole application.

All loggers propagate to the root logger, which gets:

* a console handler (stdout, UTF-8 safe)
* a rotating file handler (default: ``solar_pipeline.log``, 5 x 5 MB)

This satisfies the requirement that logs be written to BOTH the console and
a rotating file named ``solar_pipeline.log``.
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

MAX_BYTES = 5 * 1024 * 1024  # 5 MB per log file
BACKUP_COUNT = 5  # keep solar_pipeline.log.1 ... .5

FORMAT = "%(asctime)s [%(levelname)-8s] %(name)s :: %(message)s"
DATE_FMT = "%Y-%m-%d %H:%M:%S"

_configured = False


def setup_logging(log_file: str = "solar_pipeline.log", level: int = logging.INFO) -> logging.Logger:
    """Attach the console + rotating-file handlers to the root logger.

    Idempotent: safe to call multiple times (uvicorn reloads, tests, etc.).
    """
    global _configured
    if _configured:
        return logging.getLogger("solar")

    root = logging.getLogger()
    root.setLevel(level)
    formatter = logging.Formatter(FORMAT, DATE_FMT)

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(formatter)

    path = Path(log_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        path,
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)

    root.addHandler(console)
    root.addHandler(file_handler)

    # httpx/httpcore log every request at INFO by default; raise the bar so
    # only errors are surfaced (the pipeline's own ``solar`` logger stays at
    # the configured level).
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)

    _configured = True

    solar = logging.getLogger("solar")
    solar.setLevel(level)
    return solar
