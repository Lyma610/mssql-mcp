"""Operational health and ad hoc read query tools."""

from __future__ import annotations

from typing import Any

from mssql_mcp.config import Settings
from mssql_mcp.responses import success_response
from mssql_mcp.security import QueryValidator
from mssql_mcp.tools.common import DatabaseProtocol, handle_tool_errors


class QueryTools:
    def __init__(
        self,
        database: DatabaseProtocol,
        settings: Settings,
        validator: QueryValidator,
    ) -> None:
        self.database = database
        self.settings = settings
        self.validator = validator

    @handle_tool_errors(list)
    def execute_select(self, query: str) -> dict[str, Any]:
        self.validator.validate_select(query)
        page = self.database.execute_query(query, row_limit=self.settings.max_rows)
        return success_response(
            page.rows,
            row_count=len(page.rows),
            truncated=page.truncated,
            max_rows=self.settings.max_rows,
            elapsed_ms=page.elapsed_ms,
        )

    @handle_tool_errors(dict)
    def health_check(self) -> dict[str, Any]:
        latency_ms = self.database.ping()
        return success_response(
            {
                "status": "ok",
                "database": self.settings.database,
                "application_intent": self.settings.application_intent,
                "latency_ms": latency_ms,
            },
            row_count=1,
        )
