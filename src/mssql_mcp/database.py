"""ODBC access layer with bounded result fetching."""

from __future__ import annotations

import base64
import logging
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from datetime import time as time_value
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

import pyodbc

from mssql_mcp.config import Settings

logger = logging.getLogger(__name__)


class DatabaseError(RuntimeError):
    """Base database error."""


class DatabaseConnectionError(DatabaseError):
    """Raised when a SQL Server connection cannot be established."""


class QueryExecutionError(DatabaseError):
    """Raised when SQL execution fails."""


class CursorProtocol(Protocol):
    description: Sequence[Sequence[Any]] | None
    rowcount: int

    def execute(self, query: str, *params: Any) -> Any: ...

    def fetchmany(self, size: int) -> list[Any]: ...

    def fetchone(self) -> Any | None: ...

    def close(self) -> None: ...


class ConnectionProtocol(Protocol):
    timeout: int

    def cursor(self) -> CursorProtocol: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...

    def close(self) -> None: ...


ConnectFactory = Callable[..., ConnectionProtocol]


@dataclass(frozen=True, slots=True)
class QueryResult:
    rows: list[dict[str, Any]]
    truncated: bool
    elapsed_ms: int


@dataclass(frozen=True, slots=True)
class ChangeResult:
    operation: str
    affected_rows: int | None
    elapsed_ms: int


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date, time_value)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, bytes):
        return base64.b64encode(value).decode("ascii")
    return str(value)


class DatabaseManager:
    """Creates short-lived ODBC connections and executes bounded read queries."""

    def __init__(
        self,
        settings: Settings,
        connect_factory: ConnectFactory = pyodbc.connect,
    ) -> None:
        self.settings = settings
        self._connect_factory = connect_factory

    @contextmanager
    def connection(self) -> Iterator[ConnectionProtocol]:
        try:
            connection = self._connect_factory(
                self.settings.connection_string(),
                timeout=self.settings.connection_timeout,
                autocommit=False,
            )
            connection.timeout = self.settings.query_timeout
        except pyodbc.Error:
            raise DatabaseConnectionError(
                "Unable to connect to SQL Server. Verify the server, authentication, "
                "TLS settings, and ODBC driver."
            ) from None

        try:
            yield connection
        finally:
            try:
                connection.close()
            except Exception:
                logger.warning("Failed to close SQL Server connection", exc_info=True)

    def execute_query(
        self,
        query: str,
        params: Sequence[Any] = (),
        *,
        row_limit: int | None = None,
    ) -> QueryResult:
        limit = row_limit or self.settings.max_rows
        started = time.perf_counter()

        try:
            with self.connection() as connection:
                cursor = connection.cursor()
                try:
                    cursor.execute(query, *params)
                    raw_rows = cursor.fetchmany(limit + 1)
                    columns = (
                        [str(column[0]) for column in cursor.description]
                        if cursor.description
                        else []
                    )
                finally:
                    cursor.close()
        except DatabaseConnectionError:
            raise
        except pyodbc.Error as exc:
            raise QueryExecutionError(f"SQL query failed: {exc}") from exc

        truncated = len(raw_rows) > limit
        rows = [
            {column: _json_value(value) for column, value in zip(columns, row, strict=False)}
            for row in raw_rows[:limit]
        ]
        elapsed_ms = round((time.perf_counter() - started) * 1000)
        logger.info(
            "SQL query completed rows=%s truncated=%s elapsed_ms=%s",
            len(rows),
            truncated,
            elapsed_ms,
        )
        return QueryResult(rows=rows, truncated=truncated, elapsed_ms=elapsed_ms)

    def execute_scalar(self, query: str, params: Sequence[Any] = ()) -> Any | None:
        try:
            with self.connection() as connection:
                cursor = connection.cursor()
                try:
                    cursor.execute(query, *params)
                    row = cursor.fetchone()
                finally:
                    cursor.close()
        except DatabaseConnectionError:
            raise
        except pyodbc.Error as exc:
            raise QueryExecutionError(f"SQL scalar query failed: {exc}") from exc
        return _json_value(row[0]) if row else None

    def execute_change(
        self,
        query: str,
        *,
        operation: str,
        max_affected_rows: int,
    ) -> ChangeResult:
        started = time.perf_counter()
        connection: ConnectionProtocol | None = None
        cursor: CursorProtocol | None = None

        try:
            with self.connection() as connection:
                cursor = connection.cursor()
                try:
                    cursor.execute("SET XACT_ABORT ON")
                    cursor.execute(query)
                    raw_row_count = cursor.rowcount
                    affected_rows = raw_row_count if raw_row_count >= 0 else None
                    if operation in {"INSERT", "UPDATE", "DELETE"}:
                        if affected_rows is None:
                            raise QueryExecutionError(
                                "SQL Server did not report affected rows; the change was rolled back"
                            )
                        if affected_rows > max_affected_rows:
                            raise QueryExecutionError(
                                f"Change affected {affected_rows} rows, exceeding the "
                                f"configured limit of {max_affected_rows}; the change was rolled back"
                            )
                    connection.commit()
                except Exception:
                    try:
                        connection.rollback()
                    except Exception as rollback_error:
                        raise QueryExecutionError(
                            "SQL change failed and rollback also failed; transaction state is unknown"
                        ) from rollback_error
                    raise
                finally:
                    try:
                        cursor.close()
                    except Exception:
                        logger.warning("Failed to close SQL change cursor", exc_info=True)
        except DatabaseConnectionError:
            raise
        except QueryExecutionError:
            raise
        except pyodbc.Error as exc:
            raise QueryExecutionError(f"SQL change failed and was rolled back: {exc}") from exc

        elapsed_ms = round((time.perf_counter() - started) * 1000)
        logger.warning(
            "SQL change committed operation=%s affected_rows=%s elapsed_ms=%s",
            operation,
            affected_rows,
            elapsed_ms,
        )
        return ChangeResult(
            operation=operation,
            affected_rows=affected_rows,
            elapsed_ms=elapsed_ms,
        )

    def ping(self) -> int:
        started = time.perf_counter()
        result = self.execute_scalar("SELECT 1")
        if result != 1:
            raise QueryExecutionError("SQL Server health check returned an unexpected result")
        return round((time.perf_counter() - started) * 1000)
