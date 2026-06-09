"""Object dependency and source search tools."""

from __future__ import annotations

from typing import Any

from mssql_mcp.config import Settings
from mssql_mcp.responses import success_response
from mssql_mcp.security import (
    escape_like,
    validate_object_name,
    validate_search_term,
)
from mssql_mcp.tools.common import DatabaseProtocol, handle_tool_errors, pagination


class DependencyTools:
    def __init__(self, database: DatabaseProtocol, settings: Settings) -> None:
        self.database = database
        self.settings = settings

    @handle_tool_errors(dict)
    def find_table_usage(self, table_name: str) -> dict[str, Any]:
        table_name = validate_object_name(table_name, label="table name")
        query = """
            SELECT DISTINCT
                s.name AS schema_name,
                o.name AS object_name,
                CASE o.type
                    WHEN 'P' THEN 'PROCEDURE'
                    WHEN 'V' THEN 'VIEW'
                    WHEN 'FN' THEN 'SCALAR_FUNCTION'
                    WHEN 'IF' THEN 'INLINE_TABLE_FUNCTION'
                    WHEN 'TF' THEN 'TABLE_FUNCTION'
                END AS object_type,
                o.create_date,
                o.modify_date
            FROM sys.sql_expression_dependencies AS d
            INNER JOIN sys.objects AS o ON o.object_id = d.referencing_id
            INNER JOIN sys.schemas AS s ON s.schema_id = o.schema_id
            WHERE (
                    d.referenced_id = OBJECT_ID(?, 'U')
                    OR (
                        d.referenced_id IS NULL
                        AND d.referenced_entity_name = PARSENAME(?, 1)
                        AND (
                            PARSENAME(?, 2) IS NULL
                            OR d.referenced_schema_name = PARSENAME(?, 2)
                        )
                    )
                )
                AND o.type IN ('P', 'V', 'FN', 'IF', 'TF')
                AND o.is_ms_shipped = 0
            ORDER BY object_type, schema_name, object_name
        """
        page = self.database.execute_query(
            query,
            (table_name, table_name, table_name, table_name),
            row_limit=self.settings.max_rows,
        )
        grouped = _group_objects(page.rows)
        data = {
            "table_name": table_name,
            "total_dependencies": len(page.rows),
            **grouped,
        }
        return success_response(
            data,
            row_count=len(page.rows),
            truncated=page.truncated,
            elapsed_ms=page.elapsed_ms,
        )

    @handle_tool_errors(dict)
    def find_procedure_dependencies(self, procedure_name: str) -> dict[str, Any]:
        procedure_name = validate_object_name(procedure_name, label="procedure name")
        query = """
            SELECT DISTINCT
                s.name AS schema_name,
                o.name AS object_name,
                CASE o.type
                    WHEN 'U' THEN 'TABLE'
                    WHEN 'V' THEN 'VIEW'
                    WHEN 'P' THEN 'PROCEDURE'
                    WHEN 'FN' THEN 'SCALAR_FUNCTION'
                    WHEN 'IF' THEN 'INLINE_TABLE_FUNCTION'
                    WHEN 'TF' THEN 'TABLE_FUNCTION'
                END AS object_type
            FROM sys.sql_expression_dependencies AS d
            INNER JOIN sys.objects AS o ON o.object_id = d.referenced_id
            INNER JOIN sys.schemas AS s ON s.schema_id = o.schema_id
            WHERE d.referencing_id = OBJECT_ID(?, 'P')
                AND o.type IN ('U', 'V', 'P', 'FN', 'IF', 'TF')
            ORDER BY object_type, schema_name, object_name
        """
        page = self.database.execute_query(
            query,
            (procedure_name,),
            row_limit=self.settings.max_rows,
        )
        grouped = _group_objects(page.rows, include_tables=True)
        data = {
            "procedure_name": procedure_name,
            "total_dependencies": len(page.rows),
            **grouped,
        }
        return success_response(
            data,
            row_count=len(page.rows),
            truncated=page.truncated,
            elapsed_ms=page.elapsed_ms,
        )

    @handle_tool_errors(dict)
    def search_objects(
        self,
        search_term: str,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        search_term = validate_search_term(search_term)
        limit, offset = pagination(limit, offset, self.settings.max_rows)
        pattern = f"%{escape_like(search_term)}%"
        query = """
            SELECT
                s.name AS schema_name,
                o.name AS object_name,
                CASE o.type
                    WHEN 'P' THEN 'PROCEDURE'
                    WHEN 'V' THEN 'VIEW'
                    WHEN 'FN' THEN 'SCALAR_FUNCTION'
                    WHEN 'IF' THEN 'INLINE_TABLE_FUNCTION'
                    WHEN 'TF' THEN 'TABLE_FUNCTION'
                END AS object_type,
                m.definition AS object_code,
                o.create_date,
                o.modify_date
            FROM sys.objects AS o
            INNER JOIN sys.schemas AS s ON s.schema_id = o.schema_id
            INNER JOIN sys.sql_modules AS m ON m.object_id = o.object_id
            WHERE o.type IN ('P', 'V', 'FN', 'IF', 'TF')
                AND o.is_ms_shipped = 0
                AND (
                    o.name LIKE ? ESCAPE '~'
                    OR m.definition LIKE ? ESCAPE '~'
                )
            ORDER BY object_type, s.name, o.name
            OFFSET ? ROWS FETCH NEXT ? ROWS ONLY
        """
        page = self.database.execute_query(
            query,
            (pattern, pattern, offset, limit + 1),
            row_limit=limit,
        )
        normalized_term = search_term.casefold()
        for item in page.rows:
            code = str(item.pop("object_code", "") or "")
            item["occurrences"] = code.casefold().count(normalized_term)

        grouped = _group_objects(page.rows)
        data = {
            "search_term": search_term,
            "total_results": len(page.rows),
            **grouped,
        }
        return success_response(
            data,
            row_count=len(page.rows),
            limit=limit,
            offset=offset,
            has_more=page.truncated,
            elapsed_ms=page.elapsed_ms,
        )


def _group_objects(
    rows: list[dict[str, Any]],
    *,
    include_tables: bool = False,
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {
        "procedures": [],
        "views": [],
        "functions": [],
    }
    if include_tables:
        grouped["tables"] = []

    for item in rows:
        object_type = item.get("object_type")
        if object_type == "TABLE" and include_tables:
            grouped["tables"].append(item)
        elif object_type == "PROCEDURE":
            grouped["procedures"].append(item)
        elif object_type == "VIEW":
            grouped["views"].append(item)
        elif object_type in {"SCALAR_FUNCTION", "INLINE_TABLE_FUNCTION", "TABLE_FUNCTION"}:
            grouped["functions"].append(item)
    return grouped
