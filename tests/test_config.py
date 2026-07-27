import logging
from pathlib import Path

import pytest

from mssql_mcp.config import AuthenticationMode, ConfigurationError, Settings
from mssql_mcp.logging_config import JsonFormatter, configure_logging

CONFIG_ENVIRONMENT_VARIABLES = {
    "MSSQL_CONNECTION_STRING",
    "MSSQL_DRIVER",
    "MSSQL_SERVER",
    "MSSQL_DATABASE",
    "MSSQL_AUTH",
    "MSSQL_TRUSTED_CONNECTION",
    "MSSQL_USERNAME",
    "MSSQL_PASSWORD",
    "MSSQL_ENCRYPT",
    "MSSQL_TRUST_CERTIFICATE",
    "MSSQL_APPLICATION_INTENT",
    "MSSQL_TIMEOUT_CONNECTION",
    "MSSQL_TIMEOUT_QUERY",
    "MSSQL_MAX_ROWS",
    "MSSQL_MAX_QUERY_LENGTH",
    "MSSQL_ENABLE_WRITE_TOOLS",
    "MSSQL_ALLOWED_WRITE_OPERATIONS",
    "MSSQL_MAX_AFFECTED_ROWS",
    "MSSQL_CHANGE_TOKEN_TTL_SECONDS",
    "MSSQL_MAX_PENDING_CHANGES",
    "MSSQL_MCP_ENV_FILE",
    "MCP_SERVER_NAME",
    "LOG_LEVEL",
    "LOG_FORMAT",
    "LOG_FILE",
}


@pytest.fixture(autouse=True)
def isolate_configuration_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in CONFIG_ENVIRONMENT_VARIABLES:
        monkeypatch.delenv(name, raising=False)


def configure_windows_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MSSQL_SERVER", "sql.example.test")
    monkeypatch.setenv("MSSQL_DATABASE", "analytics")
    monkeypatch.setenv("MSSQL_AUTH", "windows")


def valid_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "server": "sql.example.test",
        "database": "analytics",
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def test_windows_auth_connection_string_is_read_only() -> None:
    settings = valid_settings(auth=AuthenticationMode.WINDOWS)

    settings.validate()
    connection_string = settings.connection_string()

    assert "Server={sql.example.test}" in connection_string
    assert "Database={analytics}" in connection_string
    assert "Trusted_Connection=yes" in connection_string
    assert "Encrypt=yes" in connection_string
    assert "TrustServerCertificate=yes" in connection_string
    assert "ApplicationIntent=ReadOnly" in connection_string
    assert "UID=" not in connection_string
    assert "PWD=" not in connection_string


@pytest.mark.parametrize("value", ["windows", "WINDOWS", "Windows"])
def test_windows_auth_is_case_insensitive(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    configure_windows_auth(monkeypatch)
    monkeypatch.setenv("MSSQL_AUTH", value)

    settings = Settings.from_env(env_file="missing.env")

    assert settings.auth is AuthenticationMode.WINDOWS
    assert settings.trusted_connection is True


@pytest.mark.parametrize("value", ["sql", "SQL", "Sql"])
def test_sql_auth_is_case_insensitive(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    configure_windows_auth(monkeypatch)
    monkeypatch.setenv("MSSQL_AUTH", value)
    monkeypatch.setenv("MSSQL_USERNAME", "reader")
    monkeypatch.setenv("MSSQL_PASSWORD", "secret")

    settings = Settings.from_env(env_file="missing.env")

    assert settings.auth is AuthenticationMode.SQL
    assert settings.trusted_connection is False


def test_sql_auth_builds_credential_connection_string() -> None:
    settings = valid_settings(
        auth=AuthenticationMode.SQL,
        trusted_connection=False,
        username="reader",
        password="secret}value",
    )

    settings.validate()
    connection_string = settings.connection_string()

    assert "Trusted_Connection=" not in connection_string
    assert "UID={reader}" in connection_string
    assert "PWD={secret}}value}" in connection_string


def test_sql_auth_requires_username(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_windows_auth(monkeypatch)
    monkeypatch.setenv("MSSQL_AUTH", "sql")

    with pytest.raises(
        ConfigurationError,
        match=r"^MSSQL_USERNAME is required when MSSQL_AUTH=sql\.$",
    ):
        Settings.from_env(env_file="missing.env")


def test_sql_auth_requires_password(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_windows_auth(monkeypatch)
    monkeypatch.setenv("MSSQL_AUTH", "sql")
    monkeypatch.setenv("MSSQL_USERNAME", "reader")

    with pytest.raises(
        ConfigurationError,
        match=r"^MSSQL_PASSWORD is required when MSSQL_AUTH=sql\.$",
    ):
        Settings.from_env(env_file="missing.env")


def test_explicit_auth_takes_priority_over_legacy_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_windows_auth(monkeypatch)
    monkeypatch.setenv("MSSQL_TRUSTED_CONNECTION", "no")

    settings = Settings.from_env(env_file="missing.env")

    assert settings.auth is AuthenticationMode.WINDOWS
    assert "Trusted_Connection=yes" in settings.connection_string()


@pytest.mark.parametrize(
    "trusted_value,expected_auth",
    [
        ("yes", AuthenticationMode.WINDOWS),
        ("no", AuthenticationMode.SQL),
    ],
)
def test_legacy_trusted_connection_remains_supported(
    monkeypatch: pytest.MonkeyPatch,
    trusted_value: str,
    expected_auth: AuthenticationMode,
) -> None:
    monkeypatch.setenv("MSSQL_SERVER", "sql.example.test")
    monkeypatch.setenv("MSSQL_DATABASE", "analytics")
    monkeypatch.setenv("MSSQL_TRUSTED_CONNECTION", trusted_value)
    if expected_auth is AuthenticationMode.SQL:
        monkeypatch.setenv("MSSQL_USERNAME", "reader")
        monkeypatch.setenv("MSSQL_PASSWORD", "secret")

    settings = Settings.from_env(env_file="missing.env")

    assert settings.auth is expected_auth
    assert settings.trusted_connection is (expected_auth is AuthenticationMode.WINDOWS)


def test_credentials_infer_sql_auth_for_legacy_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MSSQL_SERVER", "sql.example.test")
    monkeypatch.setenv("MSSQL_DATABASE", "analytics")
    monkeypatch.setenv("MSSQL_USERNAME", "reader")
    monkeypatch.setenv("MSSQL_PASSWORD", "secret")

    settings = Settings.from_env(env_file="missing.env")

    assert settings.auth is AuthenticationMode.SQL
    assert "UID={reader}" in settings.connection_string()


def test_authentication_must_be_determinable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MSSQL_SERVER", "sql.example.test")
    monkeypatch.setenv("MSSQL_DATABASE", "analytics")

    with pytest.raises(ConfigurationError, match="MSSQL_AUTH is required"):
        Settings.from_env(env_file="missing.env")


def test_raw_connection_string_takes_precedence_without_auth() -> None:
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


def test_internal_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_windows_auth(monkeypatch)

    settings = Settings.from_env(env_file="missing.env")

    assert settings.driver == "ODBC Driver 18 for SQL Server"
    assert settings.encrypt is True
    assert settings.trust_server_certificate is True
    assert settings.application_intent == "ReadOnly"
    assert settings.enable_write_tools is False
    assert settings.connection_timeout == 10
    assert settings.query_timeout == 30
    assert settings.max_rows == 500
    assert settings.max_query_length == 10_000


def test_environment_overrides_internal_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_windows_auth(monkeypatch)
    values = {
        "MSSQL_DRIVER": "Driver X",
        "MSSQL_ENCRYPT": "no",
        "MSSQL_TRUST_CERTIFICATE": "false",
        "MSSQL_APPLICATION_INTENT": "ReadWrite",
        "MSSQL_ENABLE_WRITE_TOOLS": "true",
        "MSSQL_TIMEOUT_CONNECTION": "12",
        "MSSQL_TIMEOUT_QUERY": "60",
        "MSSQL_MAX_ROWS": "2000",
        "MSSQL_MAX_QUERY_LENGTH": "20000",
        "MCP_SERVER_NAME": "Test server",
        "LOG_LEVEL": "debug",
        "LOG_FORMAT": "json",
        "LOG_FILE": "logs/test.log",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)

    settings = Settings.from_env(env_file="missing.env")

    assert settings.driver == "Driver X"
    assert settings.encrypt is False
    assert settings.trust_server_certificate is False
    assert settings.application_intent == "ReadWrite"
    assert settings.enable_write_tools is True
    assert settings.connection_timeout == 12
    assert settings.query_timeout == 60
    assert settings.max_rows == 2000
    assert settings.max_query_length == 20_000
    assert settings.log_level == "DEBUG"
    assert settings.log_file == Path("logs/test.log")


@pytest.mark.parametrize(
    "raw_value,expected",
    [
        ("yes", True),
        ("no", False),
        ("true", True),
        ("false", False),
        ("1", True),
        ("0", False),
        ("TRUE", True),
        ("No", False),
    ],
)
def test_boolean_parsing_is_consistent(
    monkeypatch: pytest.MonkeyPatch,
    raw_value: str,
    expected: bool,
) -> None:
    configure_windows_auth(monkeypatch)
    monkeypatch.setenv("MSSQL_ENCRYPT", raw_value)

    settings = Settings.from_env(env_file="missing.env")

    assert settings.encrypt is expected


@pytest.mark.parametrize(
    "name,value,message",
    [
        ("MSSQL_ENCRYPT", "sometimes", "must be a boolean value"),
        ("MSSQL_MAX_ROWS", "abc", "MSSQL_MAX_ROWS must be a positive integer"),
        ("MSSQL_TIMEOUT_QUERY", "-1", "MSSQL_TIMEOUT_QUERY must be a positive integer"),
        ("MSSQL_TIMEOUT_CONNECTION", "0", "must be a positive integer"),
    ],
)
def test_from_env_rejects_invalid_scalars(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
    message: str,
) -> None:
    configure_windows_auth(monkeypatch)
    monkeypatch.setenv(name, value)

    with pytest.raises(ConfigurationError, match=message):
        Settings.from_env(env_file="missing.env")


def test_from_env_rejects_invalid_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_windows_auth(monkeypatch)
    monkeypatch.setenv("MSSQL_AUTH", "invalid")

    with pytest.raises(
        ConfigurationError,
        match=r"^MSSQL_AUTH must be either 'windows' or 'sql'\.$",
    ):
        Settings.from_env(env_file="missing.env")


@pytest.mark.parametrize(
    "settings,message",
    [
        (valid_settings(driver=""), "MSSQL_DRIVER is required"),
        (Settings(database="analytics"), "MSSQL_SERVER is required"),
        (Settings(server="sql.example.test"), "MSSQL_DATABASE is required"),
        (valid_settings(application_intent="Invalid"), "MSSQL_APPLICATION_INTENT"),
        (valid_settings(log_format="xml"), "LOG_FORMAT"),
    ],
)
def test_validate_rejects_invalid_settings(settings: Settings, message: str) -> None:
    with pytest.raises(ConfigurationError, match=message):
        settings.validate()


def test_programmatic_auth_is_normalized_and_validated() -> None:
    settings = valid_settings(auth="SQL", username="reader", password="secret")

    assert settings.auth is AuthenticationMode.SQL
    assert settings.trusted_connection is False

    with pytest.raises(ConfigurationError, match="MSSQL_AUTH"):
        valid_settings(auth="invalid")


def test_required_server_and_database_errors_are_clear(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MSSQL_AUTH", "windows")

    with pytest.raises(ConfigurationError, match=r"^MSSQL_SERVER is required\.$"):
        Settings.from_env(env_file="missing.env")

    monkeypatch.setenv("MSSQL_SERVER", "sql.example.test")
    with pytest.raises(ConfigurationError, match=r"^MSSQL_DATABASE is required\.$"):
        Settings.from_env(env_file="missing.env")


def test_secret_fields_are_excluded_from_settings_repr() -> None:
    settings = valid_settings(
        raw_connection_string="Driver={Driver};PWD=raw-secret;",
        password="field-secret",
    )

    representation = repr(settings)

    assert "raw-secret" not in representation
    assert "field-secret" not in representation


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
    configure_logging(valid_settings(log_file=log_path, log_format="json"))

    logging.getLogger("test.logger").info("hello")
    for handler in logging.getLogger().handlers:
        handler.flush()

    assert '"message": "hello"' in log_path.read_text(encoding="utf-8")


def test_write_tools_require_explicit_read_write_intent() -> None:
    with pytest.raises(ConfigurationError, match="ReadWrite"):
        valid_settings(enable_write_tools=True).validate()


def test_write_operation_allowlist_is_validated() -> None:
    with pytest.raises(ConfigurationError, match="Unsupported"):
        valid_settings(allowed_write_operations=frozenset({"DROP_DATABASE"})).validate()


def test_from_env_loads_write_safety_controls(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_windows_auth(monkeypatch)
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
