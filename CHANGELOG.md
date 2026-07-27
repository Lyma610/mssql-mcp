# Changelog

All notable changes to this project are documented in this file.

## [Unreleased]

### Added
- Packaging through `pyproject.toml` and the `mssql-mcp` console command.
- A release-only PyPI Trusted Publishing workflow with artifact validation and wheel smoke tests.
- Unit-test suite, coverage enforcement, Ruff, CI, dependency audit, and Dependabot.
- `health_check`, `get_database_overview`, `list_schemas`, and `get_object_definition` tools.
- Pagination metadata and bounded cursor fetching.
- Architecture, security, contribution, and client configuration documentation.
- Opt-in `prepare_sql_change` and `execute_sql_change` tools for controlled DML and selected table/index DDL.
- Operation allowlists, exact-query fingerprints, expiring one-time tokens, transactional rollback, and DML affected-row limits.

### Changed
- Renamed the Python distribution to `lyma-mssql-mcp` while preserving the `mssql_mcp` module and `mssql-mcp` executable.
- Reorganized the implementation under `src/mssql_mcp`.
- Replaced import-time globals with factories and injectable services.
- Hardened read-query validation and parameterized internal SQL values.
- Made database availability a tool-level concern instead of a startup blocker.
- Opened ODBC connections with explicit transaction mode and added risk-accurate MCP annotations for state-changing tools.

### Removed
- Hard-coded local clients, batch scripts, machine-specific MCP configs, generated logs, bytecode, and the committed virtual environment.

## [1.0.0] - 2026-06-02

- Initial prototype with SQL Server catalog and query tools.
