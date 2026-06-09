## Summary

Describe the change and the problem it solves.

## Validation

- [ ] `ruff format --check .`
- [ ] `ruff check .`
- [ ] `pytest -m "not integration" --cov=mssql_mcp`
- [ ] Integration test performed when database behavior changed

## Security and Compatibility

- [ ] No credentials, internal server names, or production data are included
- [ ] Tool contracts and response fields remain compatible, or the breaking change is documented
- [ ] SQL Server permission and version assumptions are documented
