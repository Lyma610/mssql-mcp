import os

import pytest

from mssql_mcp.config import Settings
from mssql_mcp.database import DatabaseManager
from mssql_mcp.tools.catalog import CatalogTools

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def live_database() -> DatabaseManager:
    if os.getenv("RUN_MSSQL_INTEGRATION_TESTS") != "1":
        pytest.skip("Set RUN_MSSQL_INTEGRATION_TESTS=1 to run SQL Server integration tests")
    return DatabaseManager(Settings.from_env())


def test_live_connection(live_database: DatabaseManager) -> None:
    assert live_database.ping() >= 0


def test_live_database_overview(live_database: DatabaseManager) -> None:
    result = CatalogTools(live_database, live_database.settings).get_database_overview()

    assert result["success"] is True
    assert result["data"]["database_name"]
