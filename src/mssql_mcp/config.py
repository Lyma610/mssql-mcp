"""Centralized environment-based application configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from dotenv import load_dotenv


class ConfigurationError(ValueError):
    """Raised when environment configuration is invalid."""


class AuthenticationMode(StrEnum):
    """Supported SQL Server authentication modes."""

    WINDOWS = "windows"
    SQL = "sql"


def _as_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(f"{name} must be a boolean value (yes/no, true/false, or 1/0).")


def _as_positive_int(name: str, default: int) -> int:
    raw_value = os.getenv(name, str(default))
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be a positive integer.") from exc
    if value <= 0:
        raise ConfigurationError(f"{name} must be a positive integer.")
    return value


def _as_csv_set(name: str, default: frozenset[str]) -> frozenset[str]:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    values = frozenset(item.strip().upper() for item in raw_value.split(",") if item.strip())
    if not values:
        raise ConfigurationError(f"{name} must contain at least one value")
    return values


def _odbc_value(value: str) -> str:
    return "{" + value.replace("}", "}}") + "}"


def _normalize_auth(value: str | AuthenticationMode) -> AuthenticationMode:
    try:
        return AuthenticationMode(value.strip().lower())
    except ValueError as exc:
        raise ConfigurationError("MSSQL_AUTH must be either 'windows' or 'sql'.") from exc


def _resolve_authentication(
    *,
    allow_undetermined: bool,
) -> AuthenticationMode | None:
    explicit_auth = os.getenv("MSSQL_AUTH")
    if explicit_auth is not None:
        return _normalize_auth(explicit_auth)

    legacy_trusted_connection = os.getenv("MSSQL_TRUSTED_CONNECTION")
    if legacy_trusted_connection is not None:
        return (
            AuthenticationMode.WINDOWS
            if _as_bool("MSSQL_TRUSTED_CONNECTION", True)
            else AuthenticationMode.SQL
        )

    if os.getenv("MSSQL_USERNAME") is not None or os.getenv("MSSQL_PASSWORD") is not None:
        return AuthenticationMode.SQL

    if allow_undetermined:
        return None

    raise ConfigurationError(
        "MSSQL_AUTH is required when authentication cannot be inferred. "
        "Set MSSQL_AUTH to 'windows' or 'sql'."
    )


@dataclass(frozen=True, slots=True)
class Settings:
    """Validated runtime settings loaded from environment variables."""

    raw_connection_string: str | None = field(default=None, repr=False)
    driver: str = "ODBC Driver 18 for SQL Server"
    server: str = ""
    database: str = ""
    auth: AuthenticationMode | str | None = None
    trusted_connection: bool = True
    username: str | None = None
    password: str | None = field(default=None, repr=False)
    encrypt: bool = True
    trust_server_certificate: bool = True
    application_intent: str = "ReadOnly"
    connection_timeout: int = 10
    query_timeout: int = 30
    max_rows: int = 500
    max_query_length: int = 10_000
    enable_write_tools: bool = False
    allowed_write_operations: frozenset[str] = frozenset({"INSERT", "UPDATE", "DELETE"})
    max_affected_rows: int = 100
    change_token_ttl_seconds: int = 300
    max_pending_changes: int = 100
    server_name: str = "Microsoft SQL Server Explorer"
    log_level: str = "INFO"
    log_format: str = "plain"
    log_file: Path | None = None

    def __post_init__(self) -> None:
        mode = (
            _normalize_auth(self.auth)
            if self.auth is not None
            else (AuthenticationMode.WINDOWS if self.trusted_connection else AuthenticationMode.SQL)
        )
        object.__setattr__(self, "auth", mode)
        object.__setattr__(
            self,
            "trusted_connection",
            mode is AuthenticationMode.WINDOWS,
        )

    @classmethod
    def from_env(cls, env_file: str | Path | None = None) -> Settings:
        configured_path = env_file or os.getenv("MSSQL_MCP_ENV_FILE")
        if configured_path:
            load_dotenv(Path(configured_path), override=False)
        elif Path(".env").is_file():
            load_dotenv(".env", override=False)

        defaults = cls()
        raw_connection_string = os.getenv("MSSQL_CONNECTION_STRING") or None
        auth = _resolve_authentication(allow_undetermined=raw_connection_string is not None)
        settings = cls(
            raw_connection_string=raw_connection_string,
            driver=os.getenv("MSSQL_DRIVER", defaults.driver),
            server=os.getenv("MSSQL_SERVER", ""),
            database=os.getenv("MSSQL_DATABASE", ""),
            auth=auth,
            trusted_connection=auth is not AuthenticationMode.SQL,
            username=os.getenv("MSSQL_USERNAME") or None,
            password=os.getenv("MSSQL_PASSWORD") or None,
            encrypt=_as_bool("MSSQL_ENCRYPT", defaults.encrypt),
            trust_server_certificate=_as_bool(
                "MSSQL_TRUST_CERTIFICATE", defaults.trust_server_certificate
            ),
            application_intent=os.getenv("MSSQL_APPLICATION_INTENT", defaults.application_intent),
            connection_timeout=_as_positive_int(
                "MSSQL_TIMEOUT_CONNECTION", defaults.connection_timeout
            ),
            query_timeout=_as_positive_int("MSSQL_TIMEOUT_QUERY", defaults.query_timeout),
            max_rows=_as_positive_int("MSSQL_MAX_ROWS", defaults.max_rows),
            max_query_length=_as_positive_int("MSSQL_MAX_QUERY_LENGTH", defaults.max_query_length),
            enable_write_tools=_as_bool("MSSQL_ENABLE_WRITE_TOOLS", defaults.enable_write_tools),
            allowed_write_operations=_as_csv_set(
                "MSSQL_ALLOWED_WRITE_OPERATIONS", defaults.allowed_write_operations
            ),
            max_affected_rows=_as_positive_int(
                "MSSQL_MAX_AFFECTED_ROWS", defaults.max_affected_rows
            ),
            change_token_ttl_seconds=_as_positive_int(
                "MSSQL_CHANGE_TOKEN_TTL_SECONDS", defaults.change_token_ttl_seconds
            ),
            max_pending_changes=_as_positive_int(
                "MSSQL_MAX_PENDING_CHANGES", defaults.max_pending_changes
            ),
            server_name=os.getenv("MCP_SERVER_NAME", defaults.server_name),
            log_level=os.getenv("LOG_LEVEL", defaults.log_level).upper(),
            log_format=os.getenv("LOG_FORMAT", defaults.log_format).lower(),
            log_file=Path(value) if (value := os.getenv("LOG_FILE")) else None,
        )
        settings.validate()
        return settings

    @property
    def authentication_mode(self) -> AuthenticationMode:
        """Return normalized authentication, including programmatic legacy settings."""
        return _normalize_auth(self.auth or AuthenticationMode.WINDOWS)

    def validate(self) -> None:
        if self.raw_connection_string is not None:
            if not self.raw_connection_string.strip():
                raise ConfigurationError("MSSQL_CONNECTION_STRING cannot be empty.")
            if "\x00" in self.raw_connection_string:
                raise ConfigurationError("MSSQL_CONNECTION_STRING cannot contain null bytes.")
        else:
            if not self.driver.strip():
                raise ConfigurationError("MSSQL_DRIVER is required.")
            if not self.server.strip():
                raise ConfigurationError("MSSQL_SERVER is required.")
            if not self.database.strip():
                raise ConfigurationError("MSSQL_DATABASE is required.")
            if self.authentication_mode is AuthenticationMode.SQL:
                if not self.username:
                    raise ConfigurationError("MSSQL_USERNAME is required when MSSQL_AUTH=sql.")
                if not self.password:
                    raise ConfigurationError("MSSQL_PASSWORD is required when MSSQL_AUTH=sql.")
        supported_write_operations = {
            "INSERT",
            "UPDATE",
            "DELETE",
            "CREATE_TABLE",
            "ALTER_TABLE",
            "DROP_TABLE",
            "TRUNCATE_TABLE",
            "CREATE_INDEX",
            "ALTER_INDEX",
            "DROP_INDEX",
        }
        unknown_operations = self.allowed_write_operations - supported_write_operations
        if unknown_operations:
            unknown = ", ".join(sorted(unknown_operations))
            raise ConfigurationError(f"Unsupported MSSQL_ALLOWED_WRITE_OPERATIONS: {unknown}")
        if self.application_intent not in {"ReadOnly", "ReadWrite"}:
            raise ConfigurationError(
                "MSSQL_APPLICATION_INTENT must be either ReadOnly or ReadWrite"
            )
        if self.enable_write_tools and self.application_intent != "ReadWrite":
            raise ConfigurationError(
                "MSSQL_APPLICATION_INTENT must be ReadWrite when write tools are enabled"
            )
        if self.log_format not in {"plain", "json"}:
            raise ConfigurationError("LOG_FORMAT must be either plain or json")

    def connection_string(self) -> str:
        if self.raw_connection_string is not None:
            return self.raw_connection_string

        parts = [
            f"Driver={_odbc_value(self.driver)}",
            f"Server={_odbc_value(self.server)}",
            f"Database={_odbc_value(self.database)}",
            f"Encrypt={'yes' if self.encrypt else 'no'}",
            f"TrustServerCertificate={'yes' if self.trust_server_certificate else 'no'}",
            f"ApplicationIntent={self.application_intent}",
        ]
        if self.authentication_mode is AuthenticationMode.WINDOWS:
            parts.append("Trusted_Connection=yes")
        else:
            parts.extend(
                [
                    f"UID={_odbc_value(self.username or '')}",
                    f"PWD={_odbc_value(self.password or '')}",
                ]
            )
        return ";".join(parts) + ";"
