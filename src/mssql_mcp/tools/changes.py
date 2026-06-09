"""Explicitly approved, transactional SQL change tools."""

from __future__ import annotations

from typing import Any

from mssql_mcp.change_control import ChangeApprovalStore
from mssql_mcp.config import Settings
from mssql_mcp.responses import success_response
from mssql_mcp.security import SecurityValidationError, WriteQueryValidator
from mssql_mcp.tools.common import DatabaseProtocol, handle_tool_errors


class ChangeTools:
    def __init__(
        self,
        database: DatabaseProtocol,
        settings: Settings,
        validator: WriteQueryValidator,
        approvals: ChangeApprovalStore,
    ) -> None:
        self.database = database
        self.settings = settings
        self.validator = validator
        self.approvals = approvals

    @handle_tool_errors(dict)
    def prepare_sql_change(self, query: str) -> dict[str, Any]:
        plan = self.validator.validate_change(query)
        token, expires_at = self.approvals.issue(plan)
        return success_response(
            {
                "operation": plan.operation,
                "query_sha256": plan.query_sha256,
                "destructive": plan.destructive,
                "confirmation_token": token,
                "expires_at": expires_at,
                "warning": (
                    "Review the exact SQL statement and target database before executing. "
                    "The token is one-time and bound to this exact query."
                ),
            },
            row_count=1,
            allowed_operations=sorted(self.settings.allowed_write_operations),
            max_affected_rows=self.settings.max_affected_rows,
        )

    @handle_tool_errors(dict)
    def execute_sql_change(
        self,
        query: str,
        confirmation_token: str,
        confirm: bool,
    ) -> dict[str, Any]:
        if confirm is not True:
            raise SecurityValidationError("confirm must be true after explicit user approval")

        plan = self.validator.validate_change(query)
        self.approvals.consume(confirmation_token, plan)
        result = self.database.execute_change(
            query,
            operation=plan.operation,
            max_affected_rows=self.settings.max_affected_rows,
        )
        return success_response(
            {
                "operation": result.operation,
                "affected_rows": result.affected_rows,
                "committed": True,
                "query_sha256": plan.query_sha256,
            },
            row_count=result.affected_rows or 0,
            elapsed_ms=result.elapsed_ms,
        )
