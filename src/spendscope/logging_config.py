"""Privacy-conscious logging configuration."""

from __future__ import annotations

import logging
import logging.config
import re
from pathlib import Path
from typing import Any


class SensitiveDataFilter(logging.Filter):
    """Redact common token, card, and email-shaped values from log messages."""

    _patterns = (
        (
            re.compile(r"(?i)(access[_ -]?token|refresh[_ -]?token|authorization)(\s*[:=]\s*)\S+"),
            r"\1\2[REDACTED]",
        ),
        (re.compile(r"\b(?:\d[ -]*?){13,19}\b"), "[REDACTED CARD]"),
        (
            re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
            "[REDACTED EMAIL]",
        ),
    )

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        for pattern, replacement in self._patterns:
            message = pattern.sub(replacement, message)
        record.msg = message
        record.args = ()
        return True


def configure_logging(log_directory: Path, *, debug: bool = False) -> Path:
    log_directory.mkdir(parents=True, exist_ok=True)
    log_file = log_directory / "spendscope.log"
    config: dict[str, Any] = {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {"sensitive": {"()": SensitiveDataFilter}},
        "formatters": {
            "standard": {
                "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
                "datefmt": "%Y-%m-%dT%H:%M:%S",
            }
        },
        "handlers": {
            "file": {
                "class": "logging.handlers.RotatingFileHandler",
                "filename": str(log_file),
                "maxBytes": 1_000_000,
                "backupCount": 3,
                "encoding": "utf-8",
                "filters": ["sensitive"],
                "formatter": "standard",
            }
        },
        "root": {"level": "DEBUG" if debug else "INFO", "handlers": ["file"]},
    }
    logging.config.dictConfig(config)
    return log_file
