"""Environment-based application configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


class ConfigurationError(ValueError):
    """Raised when environment configuration is invalid."""


def _as_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(f"{name} must be a boolean value")


def _as_positive_int(name: str, default: int) -> int:
    raw_value = os.getenv(name, str(default))
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer") from exc
    if value <= 0:
        raise ConfigurationError(f"{name} must be greater than zero")
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


@dataclass(frozen=True, slots=True)
class Settings:
    """Runtime settings loaded from environment variables."""

    raw_connection_string: str | None = None
    driver: str = "ODBC Driver 18 for SQL Server"
    server: str = "localhost"
    database: str = "master"
    trusted_connection: bool = True
    username: str | None = None
    password: str | None = None
    encrypt: bool = True
    trust_server_certificate: bool = False
    application_intent: str = "ReadOnly"
    connection_timeout: int = 10
    query_timeout: int = 30
    max_rows: int = 100
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

    @classmethod
    def from_env(cls, env_file: str | Path | None = None) -> Settings:
        configured_path = env_file or os.getenv("MSSQL_MCP_ENV_FILE")
        if configured_path:
            load_dotenv(Path(configured_path), override=False)
        elif Path(".env").is_file():
            load_dotenv(".env", override=False)

        defaults = cls()
        settings = cls(
            raw_connection_string=os.getenv("MSSQL_CONNECTION_STRING") or None,
            driver=os.getenv("MSSQL_DRIVER", defaults.driver),
            server=os.getenv("MSSQL_SERVER", defaults.server),
            database=os.getenv("MSSQL_DATABASE", defaults.database),
            trusted_connection=_as_bool("MSSQL_TRUSTED_CONNECTION", True),
            username=os.getenv("MSSQL_USERNAME") or None,
            password=os.getenv("MSSQL_PASSWORD") or None,
            encrypt=_as_bool("MSSQL_ENCRYPT", True),
            trust_server_certificate=_as_bool("MSSQL_TRUST_CERTIFICATE", False),
            application_intent=os.getenv("MSSQL_APPLICATION_INTENT", "ReadOnly"),
            connection_timeout=_as_positive_int("MSSQL_TIMEOUT_CONNECTION", 10),
            query_timeout=_as_positive_int("MSSQL_TIMEOUT_QUERY", 30),
            max_rows=_as_positive_int("MSSQL_MAX_ROWS", 100),
            max_query_length=_as_positive_int("MSSQL_MAX_QUERY_LENGTH", 10_000),
            enable_write_tools=_as_bool("MSSQL_ENABLE_WRITE_TOOLS", False),
            allowed_write_operations=_as_csv_set(
                "MSSQL_ALLOWED_WRITE_OPERATIONS", defaults.allowed_write_operations
            ),
            max_affected_rows=_as_positive_int("MSSQL_MAX_AFFECTED_ROWS", 100),
            change_token_ttl_seconds=_as_positive_int("MSSQL_CHANGE_TOKEN_TTL_SECONDS", 300),
            max_pending_changes=_as_positive_int("MSSQL_MAX_PENDING_CHANGES", 100),
            server_name=os.getenv("MCP_SERVER_NAME", defaults.server_name),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
            log_format=os.getenv("LOG_FORMAT", "plain").lower(),
            log_file=Path(value) if (value := os.getenv("LOG_FILE")) else None,
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if self.raw_connection_string is not None:
            if not self.raw_connection_string.strip():
                raise ConfigurationError("MSSQL_CONNECTION_STRING cannot be empty")
            if "\x00" in self.raw_connection_string:
                raise ConfigurationError("MSSQL_CONNECTION_STRING cannot contain null bytes")
        else:
            if not self.driver.strip():
                raise ConfigurationError("MSSQL_DRIVER cannot be empty")
            if not self.server.strip():
                raise ConfigurationError("MSSQL_SERVER cannot be empty")
            if not self.database.strip():
                raise ConfigurationError("MSSQL_DATABASE cannot be empty")
            if not self.trusted_connection and not (self.username and self.password):
                raise ConfigurationError(
                    "MSSQL_USERNAME and MSSQL_PASSWORD are required when trusted connection is disabled"
                )
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
        if self.trusted_connection:
            parts.append("Trusted_Connection=yes")
        else:
            parts.extend(
                [
                    f"UID={_odbc_value(self.username or '')}",
                    f"PWD={_odbc_value(self.password or '')}",
                ]
            )
        return ";".join(parts) + ";"
