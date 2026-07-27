# Contributing

## Development setup

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
python -m pip install -e ".[dev]"
```

## Quality checks

```bash
ruff format --check .
ruff check .
pytest -m "not integration" --cov=mssql_mcp
python -m build
python -m twine check --strict dist/*
pip-audit
```

Integration tests are disabled by default. Configure a disposable read-only SQL Server target, then run:

```bash
RUN_MSSQL_INTEGRATION_TESTS=1 pytest -m integration
```

## Pull requests

- Keep changes focused and backwards compatible where practical.
- Add tests for behavioral changes and security boundaries.
- Never commit connection strings, credentials, database names, server names, or production query output.
- Update the README and changelog when the public interface changes.
- Explain database-version assumptions in the pull request description.

## Tool design

A new MCP tool should solve a distinct discovery or analysis task. Prefer extending an existing tool with optional filters or pagination when that keeps the interface simpler.
