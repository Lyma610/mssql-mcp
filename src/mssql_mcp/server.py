"""MCP server factory and command-line entry point."""

from __future__ import annotations

import logging

from mcp.server.fastmcp import FastMCP

from mssql_mcp.change_control import ChangeApprovalStore
from mssql_mcp.config import Settings
from mssql_mcp.database import DatabaseManager
from mssql_mcp.logging_config import configure_logging
from mssql_mcp.security import QueryValidator, WriteQueryValidator
from mssql_mcp.tools.catalog import CatalogTools
from mssql_mcp.tools.changes import ChangeTools
from mssql_mcp.tools.common import DatabaseProtocol
from mssql_mcp.tools.dependencies import DependencyTools
from mssql_mcp.tools.query import QueryTools
from mssql_mcp.tools.registry import register_tools
from mssql_mcp.tools.schema import SchemaTools

logger = logging.getLogger(__name__)


def create_server(
    settings: Settings | None = None,
    database: DatabaseProtocol | None = None,
) -> FastMCP:
    settings = settings or Settings.from_env()
    settings.validate()
    database = database or DatabaseManager(settings)

    instructions = (
        "Explore Microsoft SQL Server metadata and execute bounded read-oriented queries. "
        "Prefer catalog and schema tools before execute_select."
    )
    if settings.enable_write_tools:
        instructions += (
            " State-changing SQL requires prepare_sql_change followed by execute_sql_change "
            "with explicit user confirmation. Never execute a change without user approval."
        )

    mcp = FastMCP(
        name=settings.server_name,
        instructions=instructions,
        log_level=settings.log_level
        if settings.log_level in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        else "INFO",
    )
    change_tools = None
    if settings.enable_write_tools:
        change_tools = ChangeTools(
            database,
            settings,
            WriteQueryValidator.from_settings(settings),
            ChangeApprovalStore(
                settings.change_token_ttl_seconds,
                settings.max_pending_changes,
            ),
        )

    register_tools(
        mcp,
        CatalogTools(database, settings),
        SchemaTools(database),
        DependencyTools(database, settings),
        QueryTools(database, settings, QueryValidator.from_settings(settings)),
        change_tools,
    )
    return mcp


def main() -> None:
    settings = Settings.from_env()
    configure_logging(settings)
    logger.info("Starting MCP server transport=stdio name=%s", settings.server_name)
    create_server(settings).run(transport="stdio")
