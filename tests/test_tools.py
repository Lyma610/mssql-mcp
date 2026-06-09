from mssql_mcp.change_control import ChangeApprovalStore
from mssql_mcp.config import Settings
from mssql_mcp.database import ChangeResult
from mssql_mcp.security import QueryValidator, WriteQueryValidator
from mssql_mcp.tools.catalog import CatalogTools
from mssql_mcp.tools.changes import ChangeTools
from mssql_mcp.tools.dependencies import DependencyTools
from mssql_mcp.tools.query import QueryTools
from mssql_mcp.tools.schema import SchemaTools
from tests.fakes import FakeDatabase, page


def test_list_tables_uses_pagination_and_primary_partitions() -> None:
    database = FakeDatabase(
        [page([{"schema_name": "dbo", "table_name": "Orders", "row_count": 12}], truncated=True)]
    )
    tools = CatalogTools(database, Settings(max_rows=50))

    result = tools.list_tables(schema="dbo", limit=25, offset=10)

    assert result["success"] is True
    assert result["metadata"]["has_more"] is True
    query, params, row_limit = database.calls[0]
    assert "p.index_id IN (0, 1)" in query
    assert params == ("dbo", 10, 26)
    assert row_limit == 25


def test_list_databases_caps_requested_limit() -> None:
    database = FakeDatabase([page([])])
    tools = CatalogTools(database, Settings(max_rows=20))

    result = tools.list_databases(limit=500)

    assert result["metadata"]["limit"] == 20
    assert database.calls[0][1] == (0, 21)


def test_describe_table_combines_schema_details() -> None:
    database = FakeDatabase(
        [
            page([{"column_name": "id", "data_type": "int"}]),
            page([{"column_name": "id"}]),
            page([{"constraint_name": "FK_Order_Customer"}]),
            page([{"index_name": "PK_Order"}]),
        ]
    )
    tools = SchemaTools(database)

    result = tools.describe_table("dbo.Orders")

    assert result["success"] is True
    assert result["data"]["primary_key"] == ["id"]
    assert result["data"]["column_count"] == 1
    assert all(call[1] == ("dbo.Orders",) for call in database.calls)
    assert "referenced_schema.name" in database.calls[2][0]


def test_get_object_definition_supports_views() -> None:
    database = FakeDatabase(
        [
            page([{"object_name": "ActiveOrders", "object_type": "VIEW", "code": "SELECT 1"}]),
            page([]),
        ]
    )
    tools = SchemaTools(database)

    result = tools.get_object_definition("dbo.ActiveOrders", "view")

    assert result["success"] is True
    assert result["data"]["code"] == "SELECT 1"
    assert database.calls[0][1] == ("dbo.ActiveOrders", "V")
    assert "sys.schemas AS schema" not in database.calls[0][0]


def test_search_objects_parameterizes_term_and_removes_source() -> None:
    database = FakeDatabase(
        [
            page(
                [
                    {
                        "schema_name": "dbo",
                        "object_name": "GetCustomer",
                        "object_type": "PROCEDURE",
                        "object_code": "SELECT CustomerId FROM Customer",
                    }
                ]
            )
        ]
    )
    tools = DependencyTools(database, Settings(max_rows=50))

    result = tools.search_objects("Customer", limit=10)

    assert result["success"] is True
    item = result["data"]["procedures"][0]
    assert "object_code" not in item
    assert item["occurrences"] == 2
    query, params, row_limit = database.calls[0]
    assert "LIKE ?" in query
    assert "ESCAPE '~'" in query
    assert "sys.schemas AS schema" not in query
    assert params == ("%Customer%", "%Customer%", 0, 11)
    assert row_limit == 10


def test_execute_select_preserves_cte_and_reports_truncation() -> None:
    database = FakeDatabase([page([{"id": 1}], truncated=True)])
    settings = Settings(max_rows=1)
    tools = QueryTools(database, settings, QueryValidator.from_settings(settings))
    sql = "WITH x AS (SELECT 1 AS id) SELECT id FROM x"

    result = tools.execute_select(sql)

    assert result["success"] is True
    assert result["metadata"]["truncated"] is True
    assert database.calls[0] == (sql, (), 1)


def test_execute_select_returns_validation_error() -> None:
    database = FakeDatabase()
    settings = Settings()
    tools = QueryTools(database, settings, QueryValidator.from_settings(settings))

    result = tools.execute_select("SELECT * INTO dbo.Copy FROM dbo.Source")

    assert result["success"] is False
    assert "INTO" in result["error"]
    assert database.calls == []


def test_health_check_reports_latency_without_startup_probe() -> None:
    database = FakeDatabase(latency_ms=8)
    settings = Settings(database="analytics")
    tools = QueryTools(database, settings, QueryValidator.from_settings(settings))

    result = tools.health_check()

    assert result["data"] == {
        "status": "ok",
        "database": "analytics",
        "application_intent": "ReadOnly",
        "latency_ms": 8,
    }


def test_catalog_discovery_tools_and_overview() -> None:
    database = FakeDatabase(
        [
            page([{"schema_name": "dbo", "object_count": 5}]),
            page([{"schema_name": "dbo", "view_name": "ActiveOrders"}]),
            page([{"schema_name": "dbo", "procedure_name": "GetOrders"}]),
            page([{"schema_name": "dbo", "function_name": "OrderTotal"}]),
            page([{"database_name": "analytics", "table_count": 4}]),
        ]
    )
    tools = CatalogTools(database, Settings(max_rows=100))

    assert tools.list_schemas()["data"][0]["schema_name"] == "dbo"
    assert tools.list_views(schema="dbo")["data"][0]["view_name"] == "ActiveOrders"
    assert tools.list_procedures()["data"][0]["procedure_name"] == "GetOrders"
    assert tools.list_functions()["data"][0]["function_name"] == "OrderTotal"
    assert tools.get_database_overview()["data"]["database_name"] == "analytics"


def test_describe_table_returns_not_found() -> None:
    result = SchemaTools(FakeDatabase([page([])])).describe_table("dbo.Missing")

    assert result["success"] is False
    assert "not found" in result["error"]


def test_get_procedure_code_and_invalid_object_type() -> None:
    database = FakeDatabase(
        [
            page([{"object_name": "GetOrders", "object_type": "SQL_STORED_PROCEDURE"}]),
            page([{"parameter_name": "@id"}]),
        ]
    )
    tools = SchemaTools(database)

    result = tools.get_procedure_code("dbo.GetOrders")
    invalid = tools.get_object_definition("dbo.GetOrders", "trigger")

    assert result["data"]["parameter_count"] == 1
    assert invalid["success"] is False
    assert "object_type" in invalid["error"]


def test_dependency_tools_group_results() -> None:
    database = FakeDatabase(
        [
            page(
                [
                    {"object_type": "PROCEDURE", "object_name": "GetOrders"},
                    {"object_type": "VIEW", "object_name": "OrderView"},
                    {"object_type": "SCALAR_FUNCTION", "object_name": "OrderTotal"},
                ]
            ),
            page(
                [
                    {"object_type": "TABLE", "object_name": "Orders"},
                    {"object_type": "PROCEDURE", "object_name": "GetCustomer"},
                ]
            ),
        ]
    )
    tools = DependencyTools(database, Settings())

    usage = tools.find_table_usage("dbo.Orders")
    dependencies = tools.find_procedure_dependencies("dbo.GetOrders")

    assert usage["data"]["procedures"][0]["object_name"] == "GetOrders"
    assert usage["data"]["views"][0]["object_name"] == "OrderView"
    assert usage["data"]["functions"][0]["object_name"] == "OrderTotal"
    assert dependencies["data"]["tables"][0]["object_name"] == "Orders"
    assert dependencies["data"]["procedures"][0]["object_name"] == "GetCustomer"


def test_invalid_pagination_is_returned_as_validation_error() -> None:
    tools = CatalogTools(FakeDatabase(), Settings())

    negative_offset = tools.list_databases(offset=-1)
    zero_limit = tools.list_tables(limit=0)

    assert negative_offset["success"] is False
    assert "offset" in negative_offset["error"]
    assert zero_limit["success"] is False
    assert "limit" in zero_limit["error"]


def make_change_tools(database: FakeDatabase) -> ChangeTools:
    settings = Settings(
        application_intent="ReadWrite",
        enable_write_tools=True,
        allowed_write_operations=frozenset({"INSERT", "UPDATE", "DELETE", "DROP_TABLE"}),
        max_affected_rows=10,
    )
    return ChangeTools(
        database,
        settings,
        WriteQueryValidator.from_settings(settings),
        ChangeApprovalStore(300, 10),
    )


def test_prepare_and_execute_sql_change_requires_exact_one_time_token() -> None:
    database = FakeDatabase(change_result=ChangeResult("UPDATE", 2, 7))
    tools = make_change_tools(database)
    query = "UPDATE dbo.Items SET active = 0 WHERE id IN (1, 2)"

    prepared = tools.prepare_sql_change(query)
    token = prepared["data"]["confirmation_token"]
    executed = tools.execute_sql_change(query, token, True)
    repeated = tools.execute_sql_change(query, token, True)

    assert prepared["data"]["operation"] == "UPDATE"
    assert prepared["data"]["destructive"] is True
    assert executed["success"] is True
    assert executed["data"]["affected_rows"] == 2
    assert executed["data"]["committed"] is True
    assert executed["metadata"]["elapsed_ms"] == 7
    assert database.change_calls == [(query, "UPDATE", 10)]
    assert repeated["success"] is False
    assert "already used" in repeated["error"]


def test_execute_sql_change_rejects_missing_confirmation_and_changed_sql() -> None:
    database = FakeDatabase()
    tools = make_change_tools(database)
    query = "DELETE FROM dbo.Items WHERE id = 1"
    token = tools.prepare_sql_change(query)["data"]["confirmation_token"]

    not_confirmed = tools.execute_sql_change(query, token, False)
    changed = tools.execute_sql_change("DELETE FROM dbo.Items WHERE id = 2", token, True)

    assert not_confirmed["success"] is False
    assert "confirm must be true" in not_confirmed["error"]
    assert changed["success"] is False
    assert "exact prepared" in changed["error"]
    assert database.change_calls == []


def test_prepare_sql_change_rejects_non_allowlisted_operation() -> None:
    database = FakeDatabase()
    tools = make_change_tools(database)

    result = tools.prepare_sql_change("TRUNCATE TABLE dbo.Items")

    assert result["success"] is False
    assert "not enabled" in result["error"]
    assert database.change_calls == []
