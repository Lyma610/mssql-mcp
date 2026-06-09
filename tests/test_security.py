import pytest

from mssql_mcp.security import (
    QueryValidator,
    SecurityValidationError,
    WriteQueryValidator,
    escape_like,
    validate_object_name,
    validate_search_term,
)


@pytest.fixture
def validator() -> QueryValidator:
    return QueryValidator(max_query_length=1_000)


@pytest.mark.parametrize(
    "query",
    [
        "SELECT TOP 10 * FROM dbo.Customers",
        "WITH recent AS (SELECT id FROM dbo.Orders) SELECT * FROM recent",
        "SELECT 'DROP TABLE x' AS harmless_text",
        "SELECT [update] FROM dbo.Keywords;",
        "SELECT * FROM dbo.Items ORDER BY id OFFSET 10 ROWS FETCH NEXT 10 ROWS ONLY",
    ],
)
def test_accepts_read_queries(validator: QueryValidator, query: str) -> None:
    validator.validate_select(query)


@pytest.mark.parametrize(
    "query, message",
    [
        ("INSERT INTO dbo.T VALUES (1)", "Only SELECT"),
        ("SELECT * INTO dbo.Copy FROM dbo.Source", "INTO"),
        ("SELECT NEXT VALUE FOR dbo.OrderSequence", "Sequence mutation"),
        ("SELECT 1; SELECT 2", "Multiple SQL statements"),
        ("SELECT * FROM OPENROWSET('x', 'y')", "OPENROWSET"),
        ("WITH x AS (SELECT 1 AS id) DELETE FROM dbo.T", "DELETE"),
        ("SELECT * FROM dbo.T WITH (UPDLOCK)", "UPDLOCK"),
        ("SELECT 'unterminated", "unterminated"),
    ],
)
def test_rejects_unsafe_queries(
    validator: QueryValidator,
    query: str,
    message: str,
) -> None:
    with pytest.raises(SecurityValidationError, match=message):
        validator.validate_select(query)


def test_rejects_query_over_limit() -> None:
    validator = QueryValidator(max_query_length=10)

    with pytest.raises(SecurityValidationError, match="character limit"):
        validator.validate_select("SELECT 123456789")


@pytest.mark.parametrize("name", ["Customers", "dbo.Customers", "[sales].[Order Details]"])
def test_accepts_object_names(name: str) -> None:
    assert validate_object_name(name) == name


@pytest.mark.parametrize("name", ["dbo.Table;DROP", "db.schema.table", "", "dbo.*"])
def test_rejects_object_names(name: str) -> None:
    with pytest.raises(SecurityValidationError):
        validate_object_name(name)


def test_search_term_and_like_escape() -> None:
    assert validate_search_term(" customer ") == "customer"
    assert escape_like("50%_[x]~") == "50~%~_~[x]~~"


def test_rejects_short_search_term() -> None:
    with pytest.raises(SecurityValidationError, match="two characters"):
        validate_search_term("x")


def test_comments_and_escaped_identifiers_are_ignored(validator: QueryValidator) -> None:
    validator.validate_select(
        """
        -- DROP TABLE ignored
        SELECT """
        + '"up""date"'
        + """, [drop]]name], 'it''s safe'
        FROM dbo.Data /* DELETE ignored */
        """
    )


@pytest.mark.parametrize(
    "query",
    [
        "SELECT 1 /* unterminated",
        'SELECT "unterminated',
        "SELECT [unterminated",
    ],
)
def test_rejects_unterminated_sql_regions(validator: QueryValidator, query: str) -> None:
    with pytest.raises(SecurityValidationError, match="unterminated"):
        validator.validate_select(query)


def test_rejects_empty_and_non_string_queries(validator: QueryValidator) -> None:
    with pytest.raises(SecurityValidationError, match="empty"):
        validator.validate_select("  ")
    with pytest.raises(SecurityValidationError, match="empty"):
        validator.validate_select(None)  # type: ignore[arg-type]


def test_search_term_validation_rejects_invalid_values() -> None:
    with pytest.raises(SecurityValidationError, match="string"):
        validate_search_term(1)  # type: ignore[arg-type]
    with pytest.raises(SecurityValidationError, match="128"):
        validate_search_term("x" * 129)
    with pytest.raises(SecurityValidationError, match="null byte"):
        validate_search_term("ab\x00cd")


@pytest.fixture
def write_validator() -> WriteQueryValidator:
    return WriteQueryValidator(
        max_query_length=2_000,
        allowed_operations=frozenset(
            {
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
        ),
    )


@pytest.mark.parametrize(
    "query,operation",
    [
        ("INSERT INTO dbo.Items (name) VALUES ('DROP DATABASE harmless')", "INSERT"),
        ("UPDATE dbo.Items SET name = 'updated' WHERE id = 1", "UPDATE"),
        ("DELETE FROM dbo.Items WHERE id = 1", "DELETE"),
        ("CREATE TABLE dbo.TempItems (id int NOT NULL)", "CREATE_TABLE"),
        ("ALTER TABLE dbo.TempItems ADD name nvarchar(50)", "ALTER_TABLE"),
        ("DROP TABLE IF EXISTS dbo.TempItems", "DROP_TABLE"),
        ("TRUNCATE TABLE dbo.TempItems", "TRUNCATE_TABLE"),
        ("CREATE UNIQUE INDEX IX_TempItems_Id ON dbo.TempItems(id)", "CREATE_INDEX"),
        ("ALTER INDEX IX_TempItems_Id ON dbo.TempItems REBUILD", "ALTER_INDEX"),
        ("DROP INDEX IX_TempItems_Id ON dbo.TempItems", "DROP_INDEX"),
    ],
)
def test_accepts_allowlisted_write_operations(
    write_validator: WriteQueryValidator,
    query: str,
    operation: str,
) -> None:
    plan = write_validator.validate_change(query)

    assert plan.operation == operation
    assert len(plan.query_sha256) == 64


@pytest.mark.parametrize(
    "query,message",
    [
        ("UPDATE dbo.Items SET active = 0", "WHERE"),
        ("DELETE FROM dbo.Items", "WHERE"),
        ("DROP DATABASE analytics", "DATABASE"),
        ("EXEC dbo.DoSomething", "EXEC"),
        ("GRANT CONTROL TO app_user", "GRANT"),
        ("MERGE dbo.Target USING dbo.Source ON 1 = 1 WHEN MATCHED THEN DELETE", "MERGE"),
        ("INSERT INTO dbo.Items DEFAULT VALUES; DROP TABLE dbo.Items", "Multiple"),
        ("SELECT * INTO dbo.Copy FROM dbo.Source", "SELECT INTO"),
        ("DROP TABLE dbo.First, dbo.Second", "one object"),
        ("UPDATE otherdb.dbo.Items SET active = 0 WHERE id = 1", "Cross-database"),
        ("DELETE FROM [otherdb].[dbo].[Items] WHERE id = 1", "Cross-database"),
        (
            "WITH rows AS (SELECT 1 AS id) DELETE FROM dbo.Items WHERE id IN (SELECT id FROM rows)",
            "Unsupported",
        ),
    ],
)
def test_rejects_dangerous_or_ambiguous_write_sql(
    write_validator: WriteQueryValidator,
    query: str,
    message: str,
) -> None:
    with pytest.raises(SecurityValidationError, match=message):
        write_validator.validate_change(query)


def test_write_operation_must_be_explicitly_allowlisted() -> None:
    validator = WriteQueryValidator(1_000, frozenset({"INSERT"}))

    with pytest.raises(SecurityValidationError, match="not enabled"):
        validator.validate_change("DROP TABLE dbo.Items")


def test_write_fingerprint_binds_exact_query(write_validator: WriteQueryValidator) -> None:
    first = write_validator.validate_change("DELETE FROM dbo.Items WHERE id = 1")
    second = write_validator.validate_change("DELETE FROM dbo.Items WHERE id = 2")

    assert first.query_sha256 != second.query_sha256
