# Query Examples

These examples are intended for `execute_select` after catalog tools confirm object names.

## Inspect a Small Sample

```sql
SELECT TOP 20 *
FROM sales.Orders
ORDER BY OrderId DESC;
```

## Aggregate Without Returning Raw Rows

```sql
SELECT Status, COUNT(*) AS OrderCount
FROM sales.Orders
GROUP BY Status
ORDER BY OrderCount DESC;
```

## Use a CTE

```sql
WITH RecentOrders AS (
    SELECT OrderId, CustomerId, CreatedAt
    FROM sales.Orders
    WHERE CreatedAt >= DATEADD(day, -7, SYSUTCDATETIME())
)
SELECT TOP 50 *
FROM RecentOrders
ORDER BY CreatedAt DESC;
```

Avoid unfiltered scans of large tables. The response row limit controls output size, not the full amount of work SQL Server may perform.

## Controlled Changes

These examples require write tools to be enabled explicitly. Always call
`prepare_sql_change` first and execute only after reviewing the exact SQL, target
database, operation, fingerprint, and affected-row limit.

### Insert One Row

```sql
INSERT INTO sales.OrderNotes (OrderId, NoteText)
VALUES (12345, 'Reviewed through an approved MCP change');
```

### Update a Narrow Row Set

```sql
UPDATE sales.Orders
SET ReviewStatus = 'Pending'
WHERE OrderId = 12345;
```

### Delete a Narrow Row Set

```sql
DELETE FROM sales.OrderNotes
WHERE OrderNoteId = 98765;
```

DDL such as `DROP TABLE` is accepted only when its specific operation is present in
`MSSQL_ALLOWED_WRITE_OPERATIONS`. Test DDL against a disposable database, verify
backups, and use a dedicated identity without broad administrative roles.