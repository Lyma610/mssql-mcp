from datetime import datetime
from decimal import Decimal

import pyodbc
import pytest

from mssql_mcp.config import Settings
from mssql_mcp.database import (
    DatabaseConnectionError,
    DatabaseManager,
    QueryExecutionError,
)


class FakeCursor:
    def __init__(
        self,
        rows: list[tuple[object, ...]],
        *,
        execute_error: Exception | None = None,
        rowcount: int = 1,
    ) -> None:
        self.rows = rows
        self.execute_error = execute_error
        self.rowcount = rowcount
        self.description = [("created_at",), ("amount",), ("payload",)]
        self.fetch_size = 0
        self.closed = False
        self.executed: tuple[str, tuple[object, ...]] | None = None
        self.executions: list[tuple[str, tuple[object, ...]]] = []

    def execute(self, query: str, *params: object) -> None:
        if self.execute_error:
            raise self.execute_error
        self.executed = (query, params)
        self.executions.append((query, params))

    def fetchmany(self, size: int) -> list[tuple[object, ...]]:
        self.fetch_size = size
        return self.rows[:size]

    def fetchone(self) -> tuple[object, ...] | None:
        return self.rows[0] if self.rows else None

    def close(self) -> None:
        self.closed = True


class FakeConnection:
    def __init__(
        self,
        cursor: FakeCursor,
        *,
        rollback_error: Exception | None = None,
    ) -> None:
        self._cursor = cursor
        self.timeout = 0
        self.closed = False
        self.committed = False
        self.rolled_back = False
        self.rollback_error = rollback_error

    def cursor(self) -> FakeCursor:
        return self._cursor

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        if self.rollback_error:
            raise self.rollback_error
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True


def test_execute_query_fetches_only_limit_plus_one_and_serializes() -> None:
    cursor = FakeCursor(
        [
            (datetime(2026, 1, 2, 3, 4, 5), Decimal("10.25"), b"abc"),
            (datetime(2026, 1, 3), Decimal("20"), b"def"),
            (datetime(2026, 1, 4), Decimal("30"), b"ghi"),
        ]
    )
    connection = FakeConnection(cursor)
    manager = DatabaseManager(
        Settings(max_rows=2), connect_factory=lambda *args, **kwargs: connection
    )

    result = manager.execute_query("SELECT value FROM data", (7,), row_limit=2)

    assert cursor.fetch_size == 3
    assert cursor.executed == ("SELECT value FROM data", (7,))
    assert result.truncated is True
    assert len(result.rows) == 2
    assert result.rows[0] == {
        "created_at": "2026-01-02T03:04:05",
        "amount": "10.25",
        "payload": "YWJj",
    }
    assert cursor.closed is True
    assert connection.closed is True


def test_connection_failure_is_classified_separately() -> None:
    def fail_connect(*args: object, **kwargs: object) -> FakeConnection:
        raise pyodbc.Error("offline")

    manager = DatabaseManager(Settings(), connect_factory=fail_connect)

    with pytest.raises(DatabaseConnectionError, match="Unable to connect"):
        manager.execute_query("SELECT 1")


def test_connection_failure_does_not_expose_password_or_driver_exception() -> None:
    password = "do-not-leak-this-password"
    settings = Settings(
        server="sql.example.test",
        database="analytics",
        auth="sql",
        trusted_connection=False,
        username="reader",
        password=password,
    )

    def fail_connect(*args: object, **kwargs: object) -> FakeConnection:
        assert password in str(args[0])
        raise pyodbc.Error(f"Login failed for PWD={password}")

    manager = DatabaseManager(settings, connect_factory=fail_connect)

    with pytest.raises(DatabaseConnectionError) as captured:
        manager.execute_query("SELECT 1")

    assert password not in str(captured.value)
    assert captured.value.__cause__ is None


def test_query_failure_is_not_reported_as_connection_failure() -> None:
    cursor = FakeCursor([], execute_error=pyodbc.Error("bad query"))
    connection = FakeConnection(cursor)
    manager = DatabaseManager(Settings(), connect_factory=lambda *args, **kwargs: connection)

    with pytest.raises(QueryExecutionError, match="SQL query failed"):
        manager.execute_query("SELECT broken")

    assert connection.closed is True


def test_execute_scalar_and_ping() -> None:
    cursor = FakeCursor([(1, "ignored", "ignored")])
    cursor.description = [("value",)]
    connection = FakeConnection(cursor)
    manager = DatabaseManager(Settings(), connect_factory=lambda *args, **kwargs: connection)

    assert manager.execute_scalar("SELECT ?", (1,)) == 1

    second_cursor = FakeCursor([(1, "ignored", "ignored")])
    second_cursor.description = [("value",)]
    second_connection = FakeConnection(second_cursor)
    manager = DatabaseManager(Settings(), connect_factory=lambda *args, **kwargs: second_connection)
    assert manager.ping() >= 0


def test_ping_rejects_unexpected_value() -> None:
    cursor = FakeCursor([(0, "ignored", "ignored")])
    connection = FakeConnection(cursor)
    manager = DatabaseManager(Settings(), connect_factory=lambda *args, **kwargs: connection)

    with pytest.raises(QueryExecutionError, match="unexpected result"):
        manager.ping()


def test_scalar_query_failure_is_classified() -> None:
    cursor = FakeCursor([], execute_error=pyodbc.Error("bad scalar"))
    connection = FakeConnection(cursor)
    manager = DatabaseManager(Settings(), connect_factory=lambda *args, **kwargs: connection)

    with pytest.raises(QueryExecutionError, match="scalar query failed"):
        manager.execute_scalar("SELECT broken")


def test_execute_change_commits_within_affected_row_limit() -> None:
    cursor = FakeCursor([], rowcount=2)
    connection = FakeConnection(cursor)
    connect_kwargs: dict[str, object] = {}

    def connect(*args: object, **kwargs: object) -> FakeConnection:
        connect_kwargs.update(kwargs)
        return connection

    manager = DatabaseManager(Settings(), connect_factory=connect)
    result = manager.execute_change(
        "UPDATE dbo.Items SET active = 0 WHERE archived = 1",
        operation="UPDATE",
        max_affected_rows=5,
    )

    assert result.operation == "UPDATE"
    assert result.affected_rows == 2
    assert cursor.executions == [
        ("SET XACT_ABORT ON", ()),
        ("UPDATE dbo.Items SET active = 0 WHERE archived = 1", ()),
    ]
    assert connect_kwargs["autocommit"] is False
    assert connection.committed is True
    assert connection.rolled_back is False
    assert connection.closed is True


def test_execute_change_rolls_back_when_row_limit_is_exceeded() -> None:
    cursor = FakeCursor([], rowcount=101)
    connection = FakeConnection(cursor)
    manager = DatabaseManager(Settings(), connect_factory=lambda *args, **kwargs: connection)

    with pytest.raises(QueryExecutionError, match="exceeding"):
        manager.execute_change(
            "DELETE FROM dbo.Items WHERE archived = 1",
            operation="DELETE",
            max_affected_rows=100,
        )

    assert connection.committed is False
    assert connection.rolled_back is True


def test_execute_change_rolls_back_when_dml_rowcount_is_unknown() -> None:
    cursor = FakeCursor([], rowcount=-1)
    connection = FakeConnection(cursor)
    manager = DatabaseManager(Settings(), connect_factory=lambda *args, **kwargs: connection)

    with pytest.raises(QueryExecutionError, match="did not report"):
        manager.execute_change(
            "INSERT INTO dbo.Items (name) VALUES ('x')",
            operation="INSERT",
            max_affected_rows=10,
        )

    assert connection.rolled_back is True


def test_execute_change_allows_ddl_without_rowcount() -> None:
    cursor = FakeCursor([], rowcount=-1)
    connection = FakeConnection(cursor)
    manager = DatabaseManager(Settings(), connect_factory=lambda *args, **kwargs: connection)

    result = manager.execute_change(
        "DROP TABLE dbo.TempItems",
        operation="DROP_TABLE",
        max_affected_rows=10,
    )

    assert result.affected_rows is None
    assert connection.committed is True


def test_execute_change_rolls_back_driver_error() -> None:
    cursor = FakeCursor([], execute_error=pyodbc.Error("write failed"))
    connection = FakeConnection(cursor)
    manager = DatabaseManager(Settings(), connect_factory=lambda *args, **kwargs: connection)

    with pytest.raises(QueryExecutionError, match="rolled back"):
        manager.execute_change(
            "UPDATE dbo.Items SET active = 0 WHERE id = 1",
            operation="UPDATE",
            max_affected_rows=10,
        )

    assert connection.rolled_back is True


def test_execute_change_reports_unknown_state_when_rollback_fails() -> None:
    cursor = FakeCursor([], rowcount=50)
    connection = FakeConnection(cursor, rollback_error=pyodbc.Error("rollback failed"))
    manager = DatabaseManager(Settings(), connect_factory=lambda *args, **kwargs: connection)

    with pytest.raises(QueryExecutionError, match="state is unknown"):
        manager.execute_change(
            "DELETE FROM dbo.Items WHERE archived = 1",
            operation="DELETE",
            max_affected_rows=10,
        )

    assert connection.committed is False
