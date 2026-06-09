from __future__ import annotations

from typing import Any

from mssql_mcp.database import ChangeResult, QueryResult


class FakeDatabase:
    def __init__(
        self,
        pages: list[QueryResult] | None = None,
        *,
        scalar: Any = 1,
        latency_ms: int = 4,
        change_result: ChangeResult | None = None,
    ) -> None:
        self.pages = list(pages or [])
        self.scalar = scalar
        self.latency_ms = latency_ms
        self.change_result = change_result or ChangeResult("UPDATE", 1, 1)
        self.calls: list[tuple[str, tuple[Any, ...], int | None]] = []
        self.change_calls: list[tuple[str, str, int]] = []

    def execute_query(
        self,
        query: str,
        params: tuple[Any, ...] = (),
        *,
        row_limit: int | None = None,
    ) -> QueryResult:
        self.calls.append((query, params, row_limit))
        if self.pages:
            return self.pages.pop(0)
        return QueryResult(rows=[], truncated=False, elapsed_ms=1)

    def execute_scalar(self, query: str, params: tuple[Any, ...] = ()) -> Any:
        self.calls.append((query, params, None))
        return self.scalar

    def execute_change(
        self,
        query: str,
        *,
        operation: str,
        max_affected_rows: int,
    ) -> ChangeResult:
        self.change_calls.append((query, operation, max_affected_rows))
        return ChangeResult(
            operation, self.change_result.affected_rows, self.change_result.elapsed_ms
        )

    def ping(self) -> int:
        return self.latency_ms


def page(
    rows: list[dict[str, Any]],
    *,
    truncated: bool = False,
    elapsed_ms: int = 2,
) -> QueryResult:
    return QueryResult(rows=rows, truncated=truncated, elapsed_ms=elapsed_ms)
