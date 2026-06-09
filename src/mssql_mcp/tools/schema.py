"""Table and programmable object inspection tools."""

from __future__ import annotations

from typing import Any

from mssql_mcp.responses import error_response, success_response
from mssql_mcp.security import SecurityValidationError, validate_object_name
from mssql_mcp.tools.common import DatabaseProtocol, handle_tool_errors

_OBJECT_TYPES = {
    "procedure": ("P",),
    "view": ("V",),
    "function": ("FN", "IF", "TF"),
}


class SchemaTools:
    def __init__(self, database: DatabaseProtocol) -> None:
        self.database = database

    @handle_tool_errors(dict)
    def describe_table(self, table_name: str) -> dict[str, Any]:
        table_name = validate_object_name(table_name, label="table name")
        columns_query = """
            SELECT
                c.name AS column_name,
                type.name AS data_type,
                CASE
                    WHEN type.name IN ('nchar', 'nvarchar') AND c.max_length > 0
                        THEN c.max_length / 2
                    ELSE c.max_length
                END AS max_length,
                c.precision,
                c.scale,
                CAST(c.is_nullable AS BIT) AS is_nullable,
                CAST(c.is_identity AS BIT) AS is_identity,
                computed.definition AS computed_definition,
                defaults.definition AS default_value
            FROM sys.columns AS c
            INNER JOIN sys.types AS type ON type.user_type_id = c.user_type_id
            LEFT JOIN sys.computed_columns AS computed
                ON computed.object_id = c.object_id AND computed.column_id = c.column_id
            LEFT JOIN sys.default_constraints AS defaults
                ON defaults.object_id = c.default_object_id
            WHERE c.object_id = OBJECT_ID(?, 'U')
            ORDER BY c.column_id
        """
        columns_page = self.database.execute_query(columns_query, (table_name,))
        if not columns_page.rows:
            return error_response(f"Table not found or not visible: {table_name}", data={})

        primary_key_query = """
            SELECT c.name AS column_name
            FROM sys.indexes AS i
            INNER JOIN sys.index_columns AS ic
                ON ic.object_id = i.object_id AND ic.index_id = i.index_id
            INNER JOIN sys.columns AS c
                ON c.object_id = ic.object_id AND c.column_id = ic.column_id
            WHERE i.object_id = OBJECT_ID(?, 'U')
                AND i.is_primary_key = 1
            ORDER BY ic.key_ordinal
        """
        foreign_keys_query = """
            SELECT
                fk.name AS constraint_name,
                parent_column.name AS column_name,
                referenced_schema.name AS referenced_schema,
                referenced_table.name AS referenced_table,
                referenced_column.name AS referenced_column
            FROM sys.foreign_keys AS fk
            INNER JOIN sys.foreign_key_columns AS fkc ON fkc.constraint_object_id = fk.object_id
            INNER JOIN sys.columns AS parent_column
                ON parent_column.object_id = fkc.parent_object_id
                AND parent_column.column_id = fkc.parent_column_id
            INNER JOIN sys.tables AS referenced_table
                ON referenced_table.object_id = fkc.referenced_object_id
            INNER JOIN sys.schemas AS referenced_schema
                ON referenced_schema.schema_id = referenced_table.schema_id
            INNER JOIN sys.columns AS referenced_column
                ON referenced_column.object_id = fkc.referenced_object_id
                AND referenced_column.column_id = fkc.referenced_column_id
            WHERE fk.parent_object_id = OBJECT_ID(?, 'U')
            ORDER BY fk.name, fkc.constraint_column_id
        """
        indexes_query = """
            SELECT
                i.name AS index_name,
                i.type_desc AS index_type,
                STRING_AGG(QUOTENAME(c.name), ', ')
                    WITHIN GROUP (ORDER BY ic.key_ordinal, ic.index_column_id) AS columns,
                CAST(i.is_unique AS BIT) AS is_unique,
                CAST(i.is_primary_key AS BIT) AS is_primary_key,
                i.filter_definition
            FROM sys.indexes AS i
            INNER JOIN sys.index_columns AS ic
                ON ic.object_id = i.object_id AND ic.index_id = i.index_id
            INNER JOIN sys.columns AS c
                ON c.object_id = ic.object_id AND c.column_id = ic.column_id
            WHERE i.object_id = OBJECT_ID(?, 'U')
                AND i.index_id > 0
            GROUP BY i.index_id, i.name, i.type_desc, i.is_unique, i.is_primary_key, i.filter_definition
            ORDER BY i.index_id
        """
        primary_key = self.database.execute_query(primary_key_query, (table_name,))
        foreign_keys = self.database.execute_query(foreign_keys_query, (table_name,))
        indexes = self.database.execute_query(indexes_query, (table_name,))

        data = {
            "table_name": table_name,
            "columns": columns_page.rows,
            "primary_key": [row["column_name"] for row in primary_key.rows],
            "foreign_keys": foreign_keys.rows,
            "indexes": indexes.rows,
            "column_count": len(columns_page.rows),
        }
        elapsed_ms = sum(
            page.elapsed_ms for page in (columns_page, primary_key, foreign_keys, indexes)
        )
        return success_response(data, row_count=len(columns_page.rows), elapsed_ms=elapsed_ms)

    @handle_tool_errors(dict)
    def get_procedure_code(self, procedure_name: str) -> dict[str, Any]:
        procedure_name = validate_object_name(procedure_name, label="procedure name")
        return self._get_object_definition(procedure_name, ("P",))

    @handle_tool_errors(dict)
    def get_object_definition(
        self,
        object_name: str,
        object_type: str | None = None,
    ) -> dict[str, Any]:
        object_name = validate_object_name(object_name)
        if object_type is None:
            types = tuple(code for codes in _OBJECT_TYPES.values() for code in codes)
        else:
            normalized_type = object_type.strip().lower()
            if normalized_type not in _OBJECT_TYPES:
                allowed = ", ".join(sorted(_OBJECT_TYPES))
                raise SecurityValidationError(f"object_type must be one of: {allowed}")
            types = _OBJECT_TYPES[normalized_type]
        return self._get_object_definition(object_name, types)

    def _get_object_definition(
        self,
        object_name: str,
        object_types: tuple[str, ...],
    ) -> dict[str, Any]:
        placeholders = ", ".join("?" for _ in object_types)
        query = f"""
            SELECT
                s.name AS schema_name,
                o.name AS object_name,
                o.type_desc AS object_type,
                m.definition AS code,
                o.create_date,
                o.modify_date
            FROM sys.objects AS o
            INNER JOIN sys.schemas AS s ON s.schema_id = o.schema_id
            LEFT JOIN sys.sql_modules AS m ON m.object_id = o.object_id
            WHERE o.object_id = OBJECT_ID(?)
                AND o.type IN ({placeholders})
                AND o.is_ms_shipped = 0
        """
        page = self.database.execute_query(query, (object_name, *object_types), row_limit=1)
        if not page.rows:
            return error_response(f"Object not found or not visible: {object_name}", data={})

        parameters_query = """
            SELECT
                parameter.name AS parameter_name,
                TYPE_NAME(parameter.user_type_id) AS data_type,
                parameter.max_length,
                parameter.precision,
                parameter.scale,
                CAST(parameter.is_output AS BIT) AS is_output
            FROM sys.parameters AS parameter
            WHERE parameter.object_id = OBJECT_ID(?)
                AND parameter.parameter_id > 0
            ORDER BY parameter.parameter_id
        """
        parameters = self.database.execute_query(parameters_query, (object_name,))
        data = page.rows[0]
        data["parameters"] = parameters.rows
        data["parameter_count"] = len(parameters.rows)
        return success_response(
            data,
            row_count=1,
            elapsed_ms=page.elapsed_ms + parameters.elapsed_ms,
        )
