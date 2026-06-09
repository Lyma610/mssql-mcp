"""Logging configuration for stdio-safe MCP execution."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler

from mssql_mcp.config import Settings


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=True)


def configure_logging(settings: Settings) -> None:
    """Configure stderr logging and optional rotating file output."""

    level = getattr(logging, settings.log_level, logging.INFO)
    formatter: logging.Formatter
    if settings.log_format == "json":
        formatter = JsonFormatter()
    else:
        formatter = logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )

    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if settings.log_file:
        settings.log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(
            RotatingFileHandler(
                settings.log_file,
                maxBytes=5 * 1024 * 1024,
                backupCount=3,
                encoding="utf-8",
            )
        )

    for handler in handlers:
        handler.setFormatter(formatter)

    logging.basicConfig(level=level, handlers=handlers, force=True)
