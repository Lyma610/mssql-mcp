import logging
from pathlib import Path

import pytest

from mssql_mcp.config import ConfigurationError, Settings
from mssql_mcp.logging_config import JsonFormatter, configure_logging


def test_trusted_connection_string_is_read_intent() -> None:
    settings = Settings(server="db-host", database="catalog")

    connection_string = settings.connection_string()

    assert "Server={db-host}" in connection_string
    assert "Database={catalog}" in connection_string
    assert "Trusted_Connection=yes" in connection_string
    assert "ApplicationIntent=ReadOnly" in connection_string
    assert "PWD=" not in connection_string


def test_from_env_builds_windows_integrated_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MSSQL_CONNECTION_STRING", raising=False)
    monkeypatch.setenv("MSSQL_SERVER", "sql.example.test")
    monkeypatch.setenv("MSSQL_DATABASE", "analytics")
    monkeypatch.setenv("MSSQL_TRUSTED_CONNECTION", "yes")

    settings = Settings.from_env(env_file="missing.env")
    connection_string = settings.connection_string()

    assert settings.trusted_connection is True
    assert "Server={sql.example.test}" in connection_string
    assert "Database={analytics}" in connection_string
    assert "Trusted_Connection=yes" in connection_string
    assert "UID=" not in connection_string
    assert "PWD=" not in connection_string


def test_sql_auth_requires_credentials() -> None:
    settings = Settings(trusted_connection=False)

    with pytest.raises(ConfigurationError, match="MSSQL_USERNAME"):
        settings.validate()


def test_sql_auth_escapes_closing_braces() -> None:
    settings = Settings(
        trusted_connection=False,
        username="reader",
        password="secret}value",
    )

    connection_string = settings.connection_string()

    assert "UID={reader}" in connection_string
    assert "PWD={secret}}value}" in connection_string


def test_raw_connection_string_takes_precedence() -> None:
    raw_connection_string = (
        "Driver={ODBC Driver 18 for SQL Server};"
        "Server=tcp:sql.example.test,1433;"
        "Database=warehouse;UID=reader;PWD=secret;Encrypt=yes;"
    )
    settings = Settings(
        raw_connection_string=raw_connection_string,
        driver="",
        server="",
        database="",
        trusted_connection=False,
    )

    settings.validate()

    assert settings.connection_string() == raw_connection_string


def test_from_env_loads_raw_connection_string(monkeypatch: pytest.MonkeyPatch) -> None:
    raw_connection_string = "Driver={Custom Driver};Server=db;Database=warehouse;"
    monkeypatch.setenv("MSSQL_CONNECTION_STRING", raw_connection_string)

    settings = Settings.from_env(env_file="missing.env")

    assert settings.raw_connection_string == raw_connection_string
    assert settings.connection_string() == raw_connection_string


def test_from_env_loads_supported_values(monkeypatch: pytest.MonkeyPatch) -> None:
    values = {
        "MSSQL_DRIVER": "Driver X",
        "MSSQL_SERVER": "sql.example.test",
        "MSSQL_DATABASE": "warehouse",
        "MSSQL_TRUSTED_CONNECTION": "false",
        "MSSQL_USERNAME": "reader",
        "MSSQL_PASSWORD": "password",
        "MSSQL_ENCRYPT": "yes",
        "MSSQL_TRUST_CERTIFICATE": "true",
        "MSSQL_APPLICATION_INTENT": "ReadWrite",
        "MSSQL_TIMEOUT_CONNECTION": "12",
        "MSSQL_TIMEOUT_QUERY": "45",
        "MSSQL_MAX_ROWS": "250",
        "MSSQL_MAX_QUERY_LENGTH": "20000",
        "MCP_SERVER_NAME": "Test server",
        "LOG_LEVEL": "debug",
        "LOG_FORMAT": "json",
        "LOG_FILE": "logs/test.log",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)

    settings = Settings.from_env()

    assert settings.driver == "Driver X"
    assert settings.trusted_connection is False
    assert settings.username == "reader"
    assert settings.application_intent == "ReadWrite"
    assert settings.connection_timeout == 12
    assert settings.max_rows == 250
    assert settings.log_level == "DEBUG"
    assert settings.log_file is not None


@pytest.mark.parametrize(
    "name,value,message",
    [
        ("MSSQL_ENCRYPT", "sometimes", "boolean"),
        ("MSSQL_MAX_ROWS", "many", "integer"),
        ("MSSQL_TIMEOUT_QUERY", "0", "greater than zero"),
    ],
)
def test_from_env_rejects_invalid_scalars(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
    message: str,
) -> None:
    monkeypatch.setenv(name, value)

    with pytest.raises(ConfigurationError, match=message):
        Settings.from_env()


@pytest.mark.parametrize(
    "settings,message",
    [
        (Settings(driver=""), "MSSQL_DRIVER"),
        (Settings(server=""), "MSSQL_SERVER"),
        (Settings(database=""), "MSSQL_DATABASE"),
        (Settings(application_intent="Invalid"), "MSSQL_APPLICATION_INTENT"),
        (Settings(log_format="xml"), "LOG_FORMAT"),
    ],
)
def test_validate_rejects_invalid_settings(settings: Settings, message: str) -> None:
    with pytest.raises(ConfigurationError, match=message):
        settings.validate()


def test_json_formatter_serializes_exception() -> None:
    formatter = JsonFormatter()
    try:
        raise RuntimeError("failure")
    except RuntimeError:
        record = logging.LogRecord(
            "test",
            logging.ERROR,
            __file__,
            1,
            "message",
            (),
            exc_info=__import__("sys").exc_info(),
        )

    output = formatter.format(record)

    assert '"message": "message"' in output
    assert "RuntimeError: failure" in output


def test_configure_logging_writes_rotating_file(tmp_path: Path) -> None:
    log_path = tmp_path / "server.log"
    configure_logging(Settings(log_file=log_path, log_format="json"))

    logging.getLogger("test.logger").info("hello")
    for handler in logging.getLogger().handlers:
        handler.flush()

    assert '"message": "hello"' in log_path.read_text(encoding="utf-8")


def test_from_env_uses_defaults_without_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    names = [
        "MSSQL_CONNECTION_STRING",
        "MSSQL_DRIVER",
        "MSSQL_SERVER",
        "MSSQL_DATABASE",
        "MSSQL_TRUSTED_CONNECTION",
        "MSSQL_USERNAME",
        "MSSQL_PASSWORD",
        "MSSQL_APPLICATION_INTENT",
        "MSSQL_ENABLE_WRITE_TOOLS",
        "MSSQL_ALLOWED_WRITE_OPERATIONS",
        "MSSQL_MAX_AFFECTED_ROWS",
        "MSSQL_CHANGE_TOKEN_TTL_SECONDS",
        "MSSQL_MAX_PENDING_CHANGES",
        "MCP_SERVER_NAME",
    ]
    for name in names:
        monkeypatch.delenv(name, raising=False)

    settings = Settings.from_env(env_file="missing.env")

    assert settings.driver == "ODBC Driver 18 for SQL Server"
    assert settings.server == "localhost"
    assert settings.database == "master"


def test_write_tools_require_explicit_read_write_intent() -> None:
    with pytest.raises(ConfigurationError, match="ReadWrite"):
        Settings(enable_write_tools=True).validate()


def test_write_operation_allowlist_is_validated() -> None:
    with pytest.raises(ConfigurationError, match="Unsupported"):
        Settings(allowed_write_operations=frozenset({"DROP_DATABASE"})).validate()


def test_from_env_loads_write_safety_controls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MSSQL_ENABLE_WRITE_TOOLS", "yes")
    monkeypatch.setenv("MSSQL_APPLICATION_INTENT", "ReadWrite")
    monkeypatch.setenv("MSSQL_ALLOWED_WRITE_OPERATIONS", "insert, update, drop_table")
    monkeypatch.setenv("MSSQL_MAX_AFFECTED_ROWS", "25")
    monkeypatch.setenv("MSSQL_CHANGE_TOKEN_TTL_SECONDS", "120")
    monkeypatch.setenv("MSSQL_MAX_PENDING_CHANGES", "8")

    settings = Settings.from_env(env_file="missing.env")

    assert settings.enable_write_tools is True
    assert settings.allowed_write_operations == frozenset({"INSERT", "UPDATE", "DROP_TABLE"})
    assert settings.max_affected_rows == 25
    assert settings.change_token_ttl_seconds == 120
    assert settings.max_pending_changes == 8
