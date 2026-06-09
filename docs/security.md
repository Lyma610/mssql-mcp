# Security Guide

## Threat Model

The server accepts tool arguments from an AI client and sends SQL to Microsoft SQL Server. Relevant risks include unintended data changes, destructive DDL, excessive query cost, writes to the wrong database, trigger side effects, leaked credentials, metadata disclosure, and over-privileged identities.

No lexical validator can prove human intent or fully model T-SQL behavior. SQL Server permissions are the authoritative security boundary, and the MCP client must keep a human in the loop for destructive tool calls.

## Default Posture

State-changing tools are disabled by default and are not registered with the MCP server unless `MSSQL_ENABLE_WRITE_TOOLS=yes`. The default server remains read-only and `execute_select` continues to reject DML, DDL, execution, administrative commands, multiple statements, external rowsets, sequence mutation, and aggressive write locks.

## Controlled Write Workflow

When write tools are enabled, changes require two calls:

1. `prepare_sql_change` validates one exact SQL statement and returns its SHA-256 fingerprint plus a short-lived, one-time token. It does not contact or modify the database.
2. The user reviews the SQL, database, operation, and warning.
3. `execute_sql_change` receives the same SQL, the token, and `confirm=true`.
4. The server revalidates the SQL, consumes the token, opens a transaction, enables `XACT_ABORT`, executes the statement, applies the affected-row limit for DML, and commits only when every check succeeds.
5. Any validation error, driver error, unknown DML row count, or row-limit violation causes rollback.

A token is bound to the exact SQL bytes and operation, expires after `MSSQL_CHANGE_TOKEN_TTL_SECONDS`, and cannot be reused. Pending approvals are memory-only and bounded by `MSSQL_MAX_PENDING_CHANGES`.

## Operation Allowlist

`MSSQL_ALLOWED_WRITE_OPERATIONS` controls which statement families may be prepared. Supported values are:

- `INSERT`
- `UPDATE`
- `DELETE`
- `CREATE_TABLE`
- `ALTER_TABLE`
- `DROP_TABLE`
- `TRUNCATE_TABLE`
- `CREATE_INDEX`
- `ALTER_INDEX`
- `DROP_INDEX`

The default allowlist is only `INSERT,UPDATE,DELETE`. DDL must be added deliberately. `UPDATE` and `DELETE` require a top-level `WHERE`; DDL may target only one object per call; explicit three-part cross-database references are rejected.

The change validator always rejects multiple statements, CTE writes, `MERGE`, `EXEC`, dynamic or stored-procedure execution, permissions and impersonation, database/server/security-object DDL, transaction control, `USE`, `DBCC`, backup/restore, external rowsets, bulk operations, `OUTPUT`, triggers, and administrative commands.

## Least Privilege

Use a dedicated identity for this MCP server. For read-only deployments, grant only the required `SELECT` and `VIEW DEFINITION` permissions. For write-enabled deployments, grant narrowly scoped DML or object permissions only on the intended schemas and tables.

Do not use `sysadmin`, `db_owner`, broad `CONTROL`, or a developer's personal Windows identity for write-enabled production access. Prefer a separate MCP server entry and identity for writes, ideally targeting a development or sandbox database first.

Windows Authentication is supported, but the SQL permissions belong to the Windows account running the MCP client process. Verify that identity before enabling write tools.

## Resource Bounds

- Connection timeout: `MSSQL_TIMEOUT_CONNECTION`.
- Query timeout: `MSSQL_TIMEOUT_QUERY`.
- Returned row limit: `MSSQL_MAX_ROWS`.
- Query text limit: `MSSQL_MAX_QUERY_LENGTH`.
- DML affected-row limit: `MSSQL_MAX_AFFECTED_ROWS`.
- Approval lifetime: `MSSQL_CHANGE_TOKEN_TTL_SECONDS`.
- Pending approval limit: `MSSQL_MAX_PENDING_CHANGES`.

The affected-row limit is checked before commit. If the driver cannot provide a reliable DML row count, the server rolls back rather than guessing.

## Known Limitations

- Tool annotations help clients request confirmation but do not prove that a human approved the call.
- A valid statement can still express an overly broad predicate such as `WHERE 1 = 1` when the affected row count remains under the configured limit.
- Triggers, cascading foreign keys, computed expressions, synonyms, and server-side features may cause effects not visible from lexical analysis. They run within the SQL transaction where SQL Server supports that behavior.
- Explicit three-part names are blocked, but permissions and database design must still prevent indirect cross-database effects through synonyms, triggers, or programmable objects.
- DDL rollback behavior depends on SQL Server and the specific operation. Test destructive operations against disposable databases and maintain independent backups.
- `ApplicationIntent=ReadWrite` enables routing intent; it does not grant permission or prove that the target is safe.

## Deployment Checklist

- [ ] Write tools remain disabled unless there is a documented need.
- [ ] Dedicated least-privilege identity and explicit schema scope.
- [ ] `MSSQL_ALLOWED_WRITE_OPERATIONS` contains only required operations.
- [ ] Conservative `MSSQL_MAX_AFFECTED_ROWS` value.
- [ ] Client confirmation UI verified for destructive tool annotations.
- [ ] SQL Server Audit or equivalent monitoring enabled.
- [ ] Tested rollback behavior against a disposable database.
- [ ] Current backups and recovery procedure verified before enabling DDL.
- [ ] Encrypted ODBC transport with certificate validation.
- [ ] No credentials in repository files or logs.
- [ ] Unit, integration, and dependency checks passing.