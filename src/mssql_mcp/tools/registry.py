"""Registration of tool services with the MCP server."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from mssql_mcp.tools.catalog import CatalogTools
from mssql_mcp.tools.changes import ChangeTools
from mssql_mcp.tools.dependencies import DependencyTools
from mssql_mcp.tools.query import QueryTools
from mssql_mcp.tools.schema import SchemaTools

READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)

CHANGE_PREVIEW = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=False,
    openWorldHint=False,
)

DESTRUCTIVE_CHANGE = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=False,
    openWorldHint=False,
)


def register_tools(
    mcp: FastMCP,
    catalog: CatalogTools,
    schema: SchemaTools,
    dependencies: DependencyTools,
    query: QueryTools,
    changes: ChangeTools | None = None,
) -> None:
    tools: tuple[tuple[str, str, Callable[..., dict[str, Any]]], ...] = (
        (
            "list_databases",
            "List SQL Server databases visible to the configured login, with pagination.",
            catalog.list_databases,
        ),
        (
            "list_schemas",
            "List user schemas and their object counts in the selected database.",
            catalog.list_schemas,
        ),
        (
            "list_tables",
            "List user tables, optional schema filter, and approximate row counts.",
            catalog.list_tables,
        ),
        (
            "list_views",
            "List user views with optional schema filtering and pagination.",
            catalog.list_views,
        ),
        (
            "list_procedures",
            "List stored procedures, metadata, and parameter counts.",
            catalog.list_procedures,
        ),
        (
            "list_functions",
            "List scalar and table-valued functions.",
            catalog.list_functions,
        ),
        (
            "get_database_overview",
            "Return server, database, compatibility, collation, and object-count context.",
            catalog.get_database_overview,
        ),
        (
            "describe_table",
            "Describe table columns, keys, relationships, and indexes.",
            schema.describe_table,
        ),
        (
            "get_procedure_code",
            "Return a stored procedure definition and parameter metadata.",
            schema.get_procedure_code,
        ),
        (
            "get_object_definition",
            "Return the definition of a procedure, view, or function.",
            schema.get_object_definition,
        ),
        (
            "find_table_usage",
            "Find procedures, views, and functions that reference a table.",
            dependencies.find_table_usage,
        ),
        (
            "find_procedure_dependencies",
            "Find objects referenced by a stored procedure.",
            dependencies.find_procedure_dependencies,
        ),
        (
            "search_objects",
            "Search programmable object names and definitions without returning full source text.",
            dependencies.search_objects,
        ),
        (
            "execute_select",
            "Execute one validated read-oriented SELECT statement with bounded output.",
            query.execute_select,
        ),
        (
            "health_check",
            "Check SQL Server connectivity and report latency.",
            query.health_check,
        ),
    )

    for name, description, function in tools:
        mcp.tool(
            name=name,
            description=description,
            annotations=READ_ONLY,
            structured_output=True,
        )(function)

    if changes is None:
        return

    mcp.tool(
        name="prepare_sql_change",
        description=(
            "Validate one state-changing SQL statement and issue a short-lived, one-time "
            "confirmation token without modifying the database."
        ),
        annotations=CHANGE_PREVIEW,
        structured_output=True,
    )(changes.prepare_sql_change)
    mcp.tool(
        name="execute_sql_change",
        description=(
            "Execute an exactly prepared SQL change in a transaction after explicit confirmation. "
            "This tool may irreversibly modify or delete database objects and data."
        ),
        annotations=DESTRUCTIVE_CHANGE,
        structured_output=True,
    )(changes.execute_sql_change)
