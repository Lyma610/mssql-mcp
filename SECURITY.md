# Security Policy

## Reporting a vulnerability

Use GitHub private vulnerability reporting when it is enabled for the repository. Do not disclose SQL injection bypasses, credential exposure, or authorization issues in a public issue.

Include:

- affected version or commit;
- reproduction steps;
- expected and observed behavior;
- impact and required SQL Server permissions;
- any proposed mitigation.

## Security model

This server is designed for read-oriented database exploration, but application validation is only defense in depth. Deploy it with a dedicated SQL Server login that has only the minimum `SELECT` and metadata permissions required. Do not rely on query text validation as the sole authorization boundary.

See [docs/security.md](docs/security.md) for deployment guidance and known limitations.

## Supported versions

Security fixes are applied to the latest release line. Older prototype versions are not supported.
