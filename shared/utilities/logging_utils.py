"""Logging structuré commun (JSON en prod, lisible en dev)."""
from __future__ import annotations

import logging
import os
import sys


class _ColorFormatter(logging.Formatter):
    COLORS = {"DEBUG": 36, "INFO": 32, "WARNING": 33, "ERROR": 31, "CRITICAL": 41}

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, 0)
        record.msg = f"\033[{color}m{record.msg}\033[0m"
        return super().format(record)


def configure_logging(level: str | None = None) -> None:
    level = (level or os.getenv("LOG_LEVEL", "INFO")).upper()
    handler = logging.StreamHandler(sys.stdout)
    if os.getenv("LOG_FORMAT", "pretty") == "json":
        import json

        class JsonHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                print(json.dumps({
                    "ts": record.created, "level": record.levelname,
                    "logger": record.name, "msg": record.getMessage(),
                }), flush=True)

        handler = JsonHandler()
    else:
        handler.setFormatter(_ColorFormatter(
            "%(asctime)s %(levelname)-7s %(name)s — %(message)s", "%H:%M:%S"))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
