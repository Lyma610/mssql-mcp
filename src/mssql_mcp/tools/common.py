"""Shared helpers for tool services."""

from __future__ import annotations

import logging
from collections.abc import Callable
from functools import wraps
from typing import Any, ParamSpec, Protocol, TypeVar

from mssql_mcp.database import (
    ChangeResult,
    DatabaseConnectionError,
    QueryExecutionError,
    QueryResult,
)
from mssql_mcp.responses import error_response, success_response
from mssql_mcp.security import SecurityValidationError

logger = logging.getLogger(__name__)
P = ParamSpec("P")
R = TypeVar("R")


class DatabaseProtocol(Protocol):
    def execute_query(
        self,
        query: str,
        params: tuple[Any, ...] = (),
        *,
        row_limit: int | None = None,
    ) -> QueryResult: ...

    def execute_scalar(self, query: str, params: tuple[Any, ...] = ()) -> Any | None: ...

    def execute_change(
        self,
        query: str,
        *,
        operation: str,
        max_affected_rows: int,
    ) -> ChangeResult: ...

    def ping(self) -> int: ...


def handle_tool_errors(empty_data: Callable[[], Any]) -> Callable[[Callable[P, R]], Callable[P, R]]:
    def decorator(function: Callable[P, R]) -> Callable[P, R]:
        @wraps(function)
        def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
            try:
                return function(*args, **kwargs)
            except SecurityValidationError as exc:
                return error_response(f"Validation failed: {exc}", data=empty_data())  # type: ignore[return-value]
            except DatabaseConnectionError as exc:
                logger.error("Database connection failure: %s", exc)
                return error_response(str(exc), data=empty_data())  # type: ignore[return-value]
            except QueryExecutionError as exc:
                logger.error("Database query failure: %s", exc)
                return error_response(str(exc), data=empty_data())  # type: ignore[return-value]
            except Exception:
                logger.exception("Unexpected tool failure in %s", function.__name__)
                return error_response("Unexpected internal error", data=empty_data())  # type: ignore[return-value]

        return wrapped

    return decorator


def pagination(limit: int, offset: int, max_rows: int) -> tuple[int, int]:
    if not isinstance(limit, int) or limit <= 0:
        raise SecurityValidationError("limit must be a positive integer")
    if not isinstance(offset, int) or offset < 0:
        raise SecurityValidationError("offset must be zero or a positive integer")
    return min(limit, max_rows), offset


def page_response(page: QueryResult, *, limit: int, offset: int) -> dict[str, Any]:
    return success_response(
        page.rows,
        row_count=len(page.rows),
        limit=limit,
        offset=offset,
        has_more=page.truncated,
        elapsed_ms=page.elapsed_ms,
    )
