"""Database catalog discovery tools."""

from __future__ import annotations

from typing import Any

from mssql_mcp.config import Settings
from mssql_mcp.responses import success_response
from mssql_mcp.security import validate_object_name
from mssql_mcp.tools.common import (
    DatabaseProtocol,
    handle_tool_errors,
    page_response,
    pagination,
)


class CatalogTools:
    def __init__(self, database: DatabaseProtocol, settings: Settings) -> None:
        self.database = database
        self.settings = settings

    @handle_tool_errors(list)
    def list_databases(self, limit: int = 100, offset: int = 0) -> dict[str, Any]:
        limit, offset = pagination(limit, offset, self.settings.max_rows)
        query = """
            SELECT
                name AS database_name,
                state_desc AS state,
                recovery_model_desc AS recovery_model,
                compatibility_level,
                create_date
            FROM sys.databases
            ORDER BY name
            OFFSET ? ROWS FETCH NEXT ? ROWS ONLY
        """
        page = self.database.execute_query(query, (offset, limit + 1), row_limit=limit)
        return page_response(page, limit=limit, offset=offset)

    @handle_tool_errors(list)
    def list_schemas(self, limit: int = 100, offset: int = 0) -> dict[str, Any]:
        limit, offset = pagination(limit, offset, self.settings.max_rows)
        query = """
            SELECT
                s.name AS schema_name,
                USER_NAME(s.principal_id) AS owner_name,
                COUNT(o.object_id) AS object_count
            FROM sys.schemas AS s
            LEFT JOIN sys.objects AS o
                ON o.schema_id = s.schema_id
                AND o.is_ms_shipped = 0
            WHERE s.name NOT IN ('sys', 'INFORMATION_SCHEMA')
            GROUP BY s.name, s.principal_id
            ORDER BY s.name
            OFFSET ? ROWS FETCH NEXT ? ROWS ONLY
        """
        page = self.database.execute_query(query, (offset, limit + 1), row_limit=limit)
        return page_response(page, limit=limit, offset=offset)

    @handle_tool_errors(list)
    def list_tables(
        self,
        schema: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        limit, offset = pagination(limit, offset, self.settings.max_rows)
        params: list[Any] = []
        schema_filter = ""
        if schema:
            schema = validate_object_name(schema, label="schema name")
            schema_filter = "AND s.name = ?"
            params.append(schema)
        query = f"""
            SELECT
                s.name AS schema_name,
                t.name AS table_name,
                CAST(COALESCE(SUM(CASE WHEN p.index_id IN (0, 1) THEN p.rows ELSE 0 END), 0) AS BIGINT) AS row_count,
                t.create_date,
                t.modify_date
            FROM sys.tables AS t
            INNER JOIN sys.schemas AS s ON s.schema_id = t.schema_id
            LEFT JOIN sys.partitions AS p ON p.object_id = t.object_id
            WHERE t.is_ms_shipped = 0
            {schema_filter}
            GROUP BY s.name, t.name, t.create_date, t.modify_date
            ORDER BY s.name, t.name
            OFFSET ? ROWS FETCH NEXT ? ROWS ONLY
        """
        params.extend((offset, limit + 1))
        page = self.database.execute_query(query, tuple(params), row_limit=limit)
        return page_response(page, limit=limit, offset=offset)

    @handle_tool_errors(list)
    def list_views(
        self,
        schema: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        return self._list_objects(
            object_types=("V",),
            name_alias="view_name",
            schema=schema,
            limit=limit,
            offset=offset,
        )

    @handle_tool_errors(list)
    def list_procedures(
        self,
        schema: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        limit, offset = pagination(limit, offset, self.settings.max_rows)
        params: list[Any] = []
        schema_filter = ""
        if schema:
            schema = validate_object_name(schema, label="schema name")
            schema_filter = "AND s.name = ?"
            params.append(schema)
        query = f"""
            SELECT
                s.name AS schema_name,
                p.name AS procedure_name,
                p.create_date,
                p.modify_date,
                COUNT(parameter.parameter_id) AS parameter_count
            FROM sys.procedures AS p
            INNER JOIN sys.schemas AS s ON s.schema_id = p.schema_id
            LEFT JOIN sys.parameters AS parameter ON parameter.object_id = p.object_id
            WHERE p.is_ms_shipped = 0
            {schema_filter}
            GROUP BY s.name, p.name, p.create_date, p.modify_date
            ORDER BY s.name, p.name
            OFFSET ? ROWS FETCH NEXT ? ROWS ONLY
        """
        params.extend((offset, limit + 1))
        page = self.database.execute_query(query, tuple(params), row_limit=limit)
        return page_response(page, limit=limit, offset=offset)

    @handle_tool_errors(list)
    def list_functions(
        self,
        schema: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        limit, offset = pagination(limit, offset, self.settings.max_rows)
        params: list[Any] = []
        schema_filter = ""
        if schema:
            schema = validate_object_name(schema, label="schema name")
            schema_filter = "AND s.name = ?"
            params.append(schema)
        query = f"""
            SELECT
                s.name AS schema_name,
                o.name AS function_name,
                CASE o.type
                    WHEN 'FN' THEN 'SCALAR_FUNCTION'
                    WHEN 'IF' THEN 'INLINE_TABLE_FUNCTION'
                    WHEN 'TF' THEN 'TABLE_FUNCTION'
                END AS function_type,
                o.create_date,
                o.modify_date
            FROM sys.objects AS o
            INNER JOIN sys.schemas AS s ON s.schema_id = o.schema_id
            WHERE o.type IN ('FN', 'IF', 'TF')
                AND o.is_ms_shipped = 0
                {schema_filter}
            ORDER BY s.name, o.name
            OFFSET ? ROWS FETCH NEXT ? ROWS ONLY
        """
        params.extend((offset, limit + 1))
        page = self.database.execute_query(query, tuple(params), row_limit=limit)
        return page_response(page, limit=limit, offset=offset)

    @handle_tool_errors(dict)
    def get_database_overview(self) -> dict[str, Any]:
        query = """
            SELECT
                CAST(SERVERPROPERTY('ServerName') AS NVARCHAR(256)) AS server_name,
                CAST(SERVERPROPERTY('Edition') AS NVARCHAR(256)) AS edition,
                CAST(SERVERPROPERTY('ProductVersion') AS NVARCHAR(128)) AS product_version,
                DB_NAME() AS database_name,
                d.compatibility_level,
                d.collation_name,
                (SELECT COUNT(*) FROM sys.tables WHERE is_ms_shipped = 0) AS table_count,
                (SELECT COUNT(*) FROM sys.views WHERE is_ms_shipped = 0) AS view_count,
                (SELECT COUNT(*) FROM sys.procedures WHERE is_ms_shipped = 0) AS procedure_count,
                (SELECT COUNT(*) FROM sys.objects WHERE type IN ('FN', 'IF', 'TF') AND is_ms_shipped = 0) AS function_count
            FROM sys.databases AS d
            WHERE d.name = DB_NAME()
        """
        page = self.database.execute_query(query, row_limit=1)
        data = page.rows[0] if page.rows else {}
        return success_response(data, row_count=1 if data else 0, elapsed_ms=page.elapsed_ms)

    def _list_objects(
        self,
        *,
        object_types: tuple[str, ...],
        name_alias: str,
        schema: str | None,
        limit: int,
        offset: int,
    ) -> dict[str, Any]:
        limit, offset = pagination(limit, offset, self.settings.max_rows)
        params: list[Any] = list(object_types)
        placeholders = ", ".join("?" for _ in object_types)
        schema_filter = ""
        if schema:
            schema = validate_object_name(schema, label="schema name")
            schema_filter = "AND s.name = ?"
            params.append(schema)
        query = f"""
            SELECT
                s.name AS schema_name,
                o.name AS {name_alias},
                o.create_date,
                o.modify_date
            FROM sys.objects AS o
            INNER JOIN sys.schemas AS s ON s.schema_id = o.schema_id
            WHERE o.type IN ({placeholders})
                AND o.is_ms_shipped = 0
                {schema_filter}
            ORDER BY s.name, o.name
            OFFSET ? ROWS FETCH NEXT ? ROWS ONLY
        """
        params.extend((offset, limit + 1))
        page = self.database.execute_query(query, tuple(params), row_limit=limit)
        return page_response(page, limit=limit, offset=offset)
