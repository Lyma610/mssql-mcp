"""Validation for user-provided T-SQL and object names."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from mssql_mcp.config import Settings


class SecurityValidationError(ValueError):
    """Raised when user input violates a safety rule."""


_OBJECT_NAME = re.compile(
    r"^(?:\[[^\]\x00]+\]|[A-Za-z_][\w@$#]*)"
    r"(?:\.(?:\[[^\]\x00]+\]|[A-Za-z_][\w@$#]*))?$"
)
_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_@$#]*|;")
_WRITE_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_@$#]*|[();,.]")


@dataclass(frozen=True, slots=True)
class QueryValidator:
    max_query_length: int

    _forbidden_tokens = frozenset(
        {
            "ALTER",
            "BACKUP",
            "BULK",
            "CREATE",
            "DBCC",
            "DECLARE",
            "DELETE",
            "DENY",
            "DROP",
            "EXEC",
            "EXECUTE",
            "GRANT",
            "HOLDLOCK",
            "INSERT",
            "INTO",
            "KILL",
            "MERGE",
            "OPENQUERY",
            "OPENROWSET",
            "OPENDATASOURCE",
            "RECONFIGURE",
            "RESTORE",
            "REVOKE",
            "SHUTDOWN",
            "SP_CONFIGURE",
            "TABLOCKX",
            "TRUNCATE",
            "UPDATE",
            "UPDLOCK",
            "USE",
            "WAITFOR",
            "XLOCK",
            "XP_CMDSHELL",
        }
    )

    @classmethod
    def from_settings(cls, settings: Settings) -> QueryValidator:
        return cls(max_query_length=settings.max_query_length)

    def validate_select(self, query: str) -> None:
        if not isinstance(query, str) or not query.strip():
            raise SecurityValidationError("Query cannot be empty")
        if len(query) > self.max_query_length:
            raise SecurityValidationError(
                f"Query exceeds the {self.max_query_length}-character limit"
            )

        masked = _mask_literals_and_comments(query)
        statement = masked.strip()
        if statement.endswith(";"):
            statement = statement[:-1].rstrip()
        if ";" in statement:
            raise SecurityValidationError("Multiple SQL statements are not allowed")

        tokens = [token.upper() for token in _TOKEN.findall(statement)]
        if not tokens or tokens[0] not in {"SELECT", "WITH"}:
            raise SecurityValidationError("Only SELECT statements and SELECT CTEs are allowed")
        if tokens[0] == "WITH" and "SELECT" not in tokens:
            raise SecurityValidationError("A CTE must terminate in a SELECT statement")

        forbidden = sorted(set(tokens).intersection(self._forbidden_tokens))
        if forbidden:
            raise SecurityValidationError(f"Forbidden SQL token(s): {', '.join(forbidden)}")
        if _contains_sequence(tokens, ("NEXT", "VALUE", "FOR")):
            raise SecurityValidationError("Sequence mutation through NEXT VALUE FOR is not allowed")


@dataclass(frozen=True, slots=True)
class ChangePlan:
    operation: str
    query_sha256: str
    destructive: bool


@dataclass(frozen=True, slots=True)
class WriteQueryValidator:
    max_query_length: int
    allowed_operations: frozenset[str]

    _always_forbidden_tokens = frozenset(
        {
            "ASSEMBLY",
            "AUTHORIZATION",
            "BACKUP",
            "BEGIN",
            "BULK",
            "CERTIFICATE",
            "COMMIT",
            "CREDENTIAL",
            "DATABASE",
            "DBCC",
            "DECLARE",
            "DENY",
            "ENDPOINT",
            "EXEC",
            "EXECUTE",
            "GRANT",
            "IMPERSONATE",
            "KILL",
            "LOGIN",
            "MERGE",
            "OPENQUERY",
            "OPENROWSET",
            "OPENDATASOURCE",
            "OUTPUT",
            "RECONFIGURE",
            "RESTORE",
            "REVERT",
            "REVOKE",
            "ROLE",
            "ROLLBACK",
            "SAVE",
            "SCHEMA",
            "SERVER",
            "SHUTDOWN",
            "SP_CONFIGURE",
            "SWITCH",
            "TRANSACTION",
            "TRIGGER",
            "USE",
            "USER",
            "WAITFOR",
            "XP_CMDSHELL",
        }
    )

    @classmethod
    def from_settings(cls, settings: Settings) -> WriteQueryValidator:
        return cls(
            max_query_length=settings.max_query_length,
            allowed_operations=settings.allowed_write_operations,
        )

    def validate_change(self, query: str) -> ChangePlan:
        if not isinstance(query, str) or not query.strip():
            raise SecurityValidationError("Query cannot be empty")
        if len(query) > self.max_query_length:
            raise SecurityValidationError(
                f"Query exceeds the {self.max_query_length}-character limit"
            )

        masked = _mask_literals_and_comments(query)
        statement = masked.strip()
        if statement.endswith(";"):
            statement = statement[:-1].rstrip()
        if ";" in statement:
            raise SecurityValidationError("Multiple SQL statements are not allowed")

        all_tokens = [token.upper() for token in _WRITE_TOKEN.findall(statement)]
        words = [token for token in all_tokens if token not in {"(", ")", ";"}]
        if not words:
            raise SecurityValidationError("Query does not contain a SQL statement")

        forbidden = sorted(set(words).intersection(self._always_forbidden_tokens))
        if forbidden:
            raise SecurityValidationError(f"Forbidden SQL token(s): {', '.join(forbidden)}")
        if _contains_sequence(words, ("SELECT", "INTO")):
            raise SecurityValidationError("SELECT INTO is not allowed")

        top_level_tokens = _top_level_tokens(all_tokens)
        top_level = [token for token in top_level_tokens if token not in {"(", ")", ";", ",", "."}]
        operation = _classify_write_operation(top_level)
        if operation.endswith(("_TABLE", "_INDEX")) and "," in top_level_tokens:
            raise SecurityValidationError("DDL statements may target only one object at a time")
        if _contains_cross_database_reference(statement):
            raise SecurityValidationError("Cross-database write references are not allowed")
        if operation not in self.allowed_operations:
            allowed = ", ".join(sorted(self.allowed_operations))
            raise SecurityValidationError(
                f"Operation {operation} is not enabled; allowed operations: {allowed}"
            )
        if operation in {"UPDATE", "DELETE"} and "WHERE" not in top_level:
            raise SecurityValidationError(f"{operation} requires a top-level WHERE clause")

        return ChangePlan(
            operation=operation,
            query_sha256=hashlib.sha256(query.encode("utf-8")).hexdigest(),
            destructive=operation not in {"INSERT", "CREATE_TABLE", "CREATE_INDEX"},
        )


def _top_level_tokens(tokens: list[str]) -> list[str]:
    depth = 0
    result: list[str] = []
    for token in tokens:
        if token == "(":
            depth += 1
        elif token == ")":
            depth = max(0, depth - 1)
        elif token != ";" and depth == 0:
            result.append(token)
    return result


def _contains_cross_database_reference(statement: str) -> bool:
    unquoted_three_part = re.compile(
        r"\b[A-Za-z_][\w@$#]*\s*\.\s*[A-Za-z_][\w@$#]*\s*\.\s*"
        r"[A-Za-z_][\w@$#]*\b"
    )
    masked_identifier_chain = re.compile(r"(?:\.\s*\.|\.\s*[A-Za-z_][\w@$#]*\s*\.)")
    return bool(unquoted_three_part.search(statement) or masked_identifier_chain.search(statement))


def _classify_write_operation(tokens: list[str]) -> str:
    if not tokens:
        raise SecurityValidationError("Query does not contain a SQL statement")

    first = tokens[0]
    if first in {"INSERT", "UPDATE", "DELETE"}:
        return first
    if first == "TRUNCATE" and len(tokens) > 1 and tokens[1] == "TABLE":
        return "TRUNCATE_TABLE"
    if first in {"CREATE", "ALTER", "DROP"}:
        candidates = tokens[1:5]
        if "TABLE" in candidates:
            return f"{first}_TABLE"
        if "INDEX" in candidates:
            return f"{first}_INDEX"

    raise SecurityValidationError(
        "Unsupported SQL operation; use an explicitly supported DML, table, or index statement"
    )


def _contains_sequence(tokens: list[str], sequence: tuple[str, ...]) -> bool:
    width = len(sequence)
    return any(tuple(tokens[index : index + width]) == sequence for index in range(len(tokens)))


def _mask_literals_and_comments(query: str) -> str:
    output: list[str] = []
    index = 0
    state = "normal"

    while index < len(query):
        char = query[index]
        next_char = query[index + 1] if index + 1 < len(query) else ""

        if state == "normal":
            if char == "'":
                state = "string"
                output.append(" ")
            elif char == '"':
                state = "quoted_identifier"
                output.append(" ")
            elif char == "[":
                state = "bracket_identifier"
                output.append(" ")
            elif char == "-" and next_char == "-":
                state = "line_comment"
                output.extend((" ", " "))
                index += 1
            elif char == "/" and next_char == "*":
                state = "block_comment"
                output.extend((" ", " "))
                index += 1
            else:
                output.append(char)
        elif state == "string":
            output.append("\n" if char == "\n" else " ")
            if char == "'" and next_char == "'":
                output.append(" ")
                index += 1
            elif char == "'":
                state = "normal"
        elif state == "quoted_identifier":
            output.append("\n" if char == "\n" else " ")
            if char == '"' and next_char == '"':
                output.append(" ")
                index += 1
            elif char == '"':
                state = "normal"
        elif state == "bracket_identifier":
            output.append("\n" if char == "\n" else " ")
            if char == "]" and next_char == "]":
                output.append(" ")
                index += 1
            elif char == "]":
                state = "normal"
        elif state == "line_comment":
            output.append("\n" if char == "\n" else " ")
            if char == "\n":
                state = "normal"
        elif state == "block_comment":
            output.append("\n" if char == "\n" else " ")
            if char == "*" and next_char == "/":
                output.append(" ")
                index += 1
                state = "normal"
        index += 1

    if state in {"string", "quoted_identifier", "bracket_identifier", "block_comment"}:
        raise SecurityValidationError(
            "Query contains an unterminated literal, identifier, or comment"
        )
    return "".join(output)


def validate_object_name(value: str, *, label: str = "object name") -> str:
    if not isinstance(value, str) or not value.strip():
        raise SecurityValidationError(f"{label.capitalize()} cannot be empty")
    normalized = value.strip()
    if len(normalized) > 257 or not _OBJECT_NAME.fullmatch(normalized):
        raise SecurityValidationError(f"Invalid {label}: {value}")
    return normalized


def validate_search_term(value: str) -> str:
    if not isinstance(value, str):
        raise SecurityValidationError("Search term must be a string")
    normalized = value.strip()
    if len(normalized) < 2:
        raise SecurityValidationError("Search term must contain at least two characters")
    if len(normalized) > 128:
        raise SecurityValidationError("Search term cannot exceed 128 characters")
    if "\x00" in normalized:
        raise SecurityValidationError("Search term contains an invalid null byte")
    return normalized


def escape_like(value: str) -> str:
    return value.replace("~", "~~").replace("%", "~%").replace("_", "~_").replace("[", "~[")
