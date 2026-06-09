"""Validate local configuration and SQL Server connectivity."""

from __future__ import annotations

import json

from mssql_mcp.config import ConfigurationError, Settings
from mssql_mcp.database import DatabaseError, DatabaseManager


def main() -> int:
    try:
        settings = Settings.from_env()
        latency_ms = DatabaseManager(settings).ping()
    except (ConfigurationError, DatabaseError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=True))
        return 1

    print(
        json.dumps(
            {
                "status": "ok",
                "database": settings.database,
                "application_intent": settings.application_intent,
                "latency_ms": latency_ms,
            },
            ensure_ascii=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
