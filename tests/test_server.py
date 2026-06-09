import asyncio

from mssql_mcp.config import Settings
from mssql_mcp.server import create_server
from tests.fakes import FakeDatabase

EXPECTED_TOOLS = {
    "describe_table",
    "execute_select",
    "find_procedure_dependencies",
    "find_table_usage",
    "get_database_overview",
    "get_object_definition",
    "get_procedure_code",
    "health_check",
    "list_databases",
    "list_functions",
    "list_procedures",
    "list_schemas",
    "list_tables",
    "list_views",
    "search_objects",
}


def test_server_registers_expected_read_only_tools_by_default() -> None:
    server = create_server(Settings(), FakeDatabase())

    tools = asyncio.run(server.list_tools())

    assert {tool.name for tool in tools} == EXPECTED_TOOLS
    assert all(tool.annotations and tool.annotations.readOnlyHint for tool in tools)
    assert all(tool.annotations and tool.annotations.destructiveHint is False for tool in tools)


def test_server_registers_opt_in_change_tools_with_risk_annotations() -> None:
    settings = Settings(
        application_intent="ReadWrite",
        enable_write_tools=True,
        allowed_write_operations=frozenset({"INSERT", "UPDATE", "DELETE"}),
    )
    server = create_server(settings, FakeDatabase())

    tools = {tool.name: tool for tool in asyncio.run(server.list_tools())}

    assert set(tools) == EXPECTED_TOOLS | {"prepare_sql_change", "execute_sql_change"}
    preview = tools["prepare_sql_change"].annotations
    execute = tools["execute_sql_change"].annotations
    assert preview and preview.readOnlyHint is True
    assert preview.destructiveHint is False
    assert execute and execute.readOnlyHint is False
    assert execute.destructiveHint is True
    assert execute.idempotentHint is False
