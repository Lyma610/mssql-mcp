# Architecture

## Components

### Configuration

`mssql_mcp.config.Settings` is the single configuration boundary. It loads environment variables,
applies typed defaults, normalizes boolean and integer values, resolves Windows or SQL
authentication, validates resource bounds and write opt-in, and builds the ODBC connection string.
Authentication resolution prioritizes explicit `MSSQL_AUTH`, then the legacy trusted-connection
flag, then the presence of SQL credentials. Loading configuration is explicit; importing the
package has no runtime side effects.

### Logging

`mssql_mcp.logging_config` configures stderr logging for MCP `stdio` compatibility. JSON formatting and rotating file output are optional. SQL text, credentials, and confirmation tokens are not written by the application logger.

### Database Layer

`DatabaseManager` owns short-lived ODBC connections, query timeouts, bounded reads, JSON-safe value conversion, and transactional changes. Connections use `autocommit=False`. State-changing statements execute with `XACT_ABORT ON`, commit explicitly, and roll back on any failure or DML row-limit violation.

The tool layer depends on `DatabaseProtocol`, not the concrete manager, so tests use deterministic fakes.

### Validation

`QueryValidator` enforces the read-only `execute_select` contract. `WriteQueryValidator` is a separate conservative validator for the explicitly supported write families. Both mask strings, comments, and quoted identifiers before evaluating structure and forbidden tokens.

Keeping the validators separate prevents write enablement from weakening read-query rules.

### Change Control

`ChangeApprovalStore` holds bounded, short-lived approvals in memory. It stores only operation, fingerprint, and expiration, not SQL text. Tokens are cryptographically random, one-time, and bound to the exact query fingerprint.

`ChangeTools` implements the two-step prepare/execute workflow. The service is constructed and registered only when write tools are enabled.

### Tool Services

- `CatalogTools`: server/database context and catalog listings.
- `SchemaTools`: table details and SQL object definitions.
- `DependencyTools`: dependency graph queries and source search.
- `QueryTools`: connectivity health and bounded ad hoc reads.
- `ChangeTools`: opt-in preparation and transactional execution of allowlisted changes.
- `registry.py`: stable MCP names, descriptions, risk annotations, and structured output registration.

### Server Factory

`create_server()` validates settings, wires dependencies, and returns `FastMCP`. With default settings it registers 15 read-only tools. With write tools enabled it additionally registers `prepare_sql_change` and `execute_sql_change`.

## Read Request Flow

1. The MCP client invokes a read tool.
2. FastMCP validates the Python input schema.
3. The service validates identifiers, pagination, or T-SQL.
4. The database layer executes parameterized metadata SQL or one validated `SELECT`.
5. Rows are fetched with a configured bound and normalized to JSON-safe values.
6. The service returns the stable response envelope.

## Change Request Flow

1. The client calls `prepare_sql_change` with one SQL statement.
2. `WriteQueryValidator` classifies the operation and checks the allowlist and safety rules.
3. `ChangeApprovalStore` returns a one-time token bound to the exact SHA-256 fingerprint.
4. After user review, the client calls `execute_sql_change` with unchanged SQL, token, and `confirm=true`.
5. The server revalidates and consumes the approval before opening the transaction.
6. `DatabaseManager` executes with `XACT_ABORT ON` and `autocommit=False`.
7. DML commits only when the affected-row count is known and within the configured limit; otherwise it rolls back.
8. The response reports operation, fingerprint, affected rows, commit status, and elapsed time.

## Design Decisions

### Writes are absent by default

Conditional registration is stronger than exposing a disabled generic executor. Clients cannot discover or invoke change tools unless the operator opts in before server startup.

### Exact-query confirmation

The approval token binds the preparation and execution calls without persisting SQL text. Any whitespace or content change produces a different fingerprint and invalidates the token.

### One connection per operation

Short-lived connections rely on ODBC pooling, isolate failures, and avoid shared transaction or cursor state.

### Stable envelopes

All tools return `success`, `data`, `row_count`, `error`, and `metadata`, including validation and rollback failures.

## Extension Points

- Add a new write family only by extending the supported operation set, classifier, security tests, documentation, and least-privilege guidance together.
- Implement `DatabaseProtocol` for another driver while preserving transaction and rollback guarantees.
- Add database/schema allowlists if controlled multi-database operation is introduced.
- Add durable audit events through a dedicated sink without logging SQL literals or credentials.
