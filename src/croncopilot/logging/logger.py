"""Logging utilities for CronCopilot.

Provides JSON-formatted log output via ``JsonFormatter`` and helper
functions to bootstrap the application logging configuration.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path


class JsonFormatter(logging.Formatter):
    """A ``logging.Formatter`` that outputs each record as a JSON object.

    Fields included: ``timestamp``, ``level``, ``name``, ``message``,
    and any *extra* attributes attached to the log record.
    """

    # Attributes that belong to the base LogRecord and should not be
    # forwarded as "extra" fields.
    _BUILTIN_ATTRS: frozenset[str] = frozenset(
        {
            "args",
            "created",
            "exc_info",
            "exc_text",
            "filename",
            "funcName",
            "levelname",
            "levelno",
            "lineno",
            "message",
            "module",
            "msecs",
            "msg",
            "name",
            "pathname",
            "process",
            "processName",
            "relativeCreated",
            "stack_info",
            "taskName",
            "thread",
            "threadName",
        }
    )

    def format(self, record: logging.LogRecord) -> str:
        """Format *record* as a single-line JSON string.

        Parameters:
            record: The log record to format.

        Returns:
            JSON-encoded log line.
        """
        record.message = record.getMessage()

        log_entry: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "name": record.name,
            "message": record.message,
        }

        # Attach any extra fields the caller added.
        for key, value in record.__dict__.items():
            if key not in self._BUILTIN_ATTRS and not key.startswith("_"):
                log_entry[key] = value

        if record.exc_info and not record.exc_text:
            record.exc_text = self.formatException(record.exc_info)
        if record.exc_text:
            log_entry["exception"] = record.exc_text
        if record.stack_info:
            log_entry["stack_info"] = record.stack_info

        return json.dumps(log_entry, ensure_ascii=False, default=str)


_STANDARD_FORMAT = "%(asctime)s [%(levelname)-8s] %(name)s - %(message)s"


def setup_logging(
    log_dir: str,
    level: str = "INFO",
    max_days: int = 30,
    json_format: bool = True,
) -> None:
    """Configure the root logger for CronCopilot.

    * Creates *log_dir* if it does not exist.
    * Adds a ``TimedRotatingFileHandler`` that rotates daily and keeps
      files for *max_days*.
    * Adds a ``StreamHandler`` for console output.
    * Applies ``JsonFormatter`` when *json_format* is ``True``;
      otherwise uses a human-readable format.

    Parameters:
        log_dir: Directory where log files are written.
        level: Logging level name (``DEBUG``, ``INFO``, …).
        max_days: Number of days to retain rotated log files.
        json_format: If ``True``, use JSON-formatted output.
    """
    log_dir = os.path.expanduser(log_dir)
    Path(log_dir).mkdir(parents=True, exist_ok=True)

    log_level = getattr(logging, level.upper(), logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Avoid adding duplicate handlers on repeated calls.
    root_logger.handlers.clear()

    # Choose formatter.
    formatter: logging.Formatter
    if json_format:
        formatter = JsonFormatter()
    else:
        formatter = logging.Formatter(_STANDARD_FORMAT)

    # File handler – one file per day, kept for *max_days*.
    log_file = os.path.join(log_dir, "croncopilot.log")
    file_handler = TimedRotatingFileHandler(
        filename=log_file,
        when="midnight",
        interval=1,
        backupCount=max_days,
        encoding="utf-8",
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    # Console handler.
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)


def get_logger(name: str) -> logging.Logger:
    """Return a named logger.

    Parameters:
        name: Dot-separated logger name (e.g. ``croncopilot.core``).

    Returns:
        logging.Logger: The requested logger instance.
    """
    return logging.getLogger(name)
