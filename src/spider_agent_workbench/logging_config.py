"""
Shared logging setup for phase scripts and eval runs.

Configures the root logger with two handlers — console (stdout) and a
timestamped file under logs/ — so any module can just call
`logging.getLogger(__name__)` and have its output land in both places,
including across the worker threads used by phase_1_test.py (the stdlib
logging module is thread-safe).
"""

from __future__ import annotations

import logging
from datetime import datetime

from spider_agent_workbench import paths

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# These log every HTTP call at INFO (e.g. "HTTP Request: POST .../messages
# 200 OK") via the Anthropic SDK's httpx client — noise once root has
# handlers attached, so keep them at WARNING regardless of `level`.
NOISY_LOGGERS = ("httpx", "httpcore")


def setup_logging(phase_number: int | str, level: int = logging.INFO) -> logging.Logger:
    """Configure the root logger to write to both stdout and
    logs/phase_<phase_number>_<YYYY-MM-DD-HH-MM>.log, and return it.

    Clears any handlers from a prior call so re-running in the same
    process doesn't duplicate log lines across handlers.
    """
    paths.LOGS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d-%H")
    log_path = paths.LOGS_DIR / f"phase_{phase_number}_{timestamp}.log"

    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(level)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    for noisy_name in NOISY_LOGGERS:
        logging.getLogger(noisy_name).setLevel(logging.WARNING)

    root_logger.info("Logging to %s", log_path)
    return root_logger
