from datetime import UTC, datetime

import pytest

from mssql_mcp.change_control import ChangeApprovalStore
from mssql_mcp.security import ChangePlan, SecurityValidationError


def plan(digest: str = "a" * 64) -> ChangePlan:
    return ChangePlan("UPDATE", digest, True)


def test_approval_is_bound_and_one_time() -> None:
    store = ChangeApprovalStore(300, 10)
    token, expires_at = store.issue(plan())

    assert expires_at.endswith("+00:00")
    store.consume(token, plan())

    with pytest.raises(SecurityValidationError, match="already used"):
        store.consume(token, plan())


def test_mismatched_query_consumes_token() -> None:
    store = ChangeApprovalStore(300, 10)
    token, _ = store.issue(plan())

    with pytest.raises(SecurityValidationError, match="exact prepared"):
        store.consume(token, plan("b" * 64))
    with pytest.raises(SecurityValidationError, match="already used"):
        store.consume(token, plan())


def test_expired_and_capacity_limited_approvals() -> None:
    now = [10.0]
    store = ChangeApprovalStore(
        5,
        1,
        monotonic_clock=lambda: now[0],
        utc_clock=lambda: datetime(2026, 6, 9, tzinfo=UTC),
    )
    token, _ = store.issue(plan())

    with pytest.raises(SecurityValidationError, match="Too many"):
        store.issue(plan("b" * 64))

    now[0] = 16.0
    with pytest.raises(SecurityValidationError, match="expired"):
        store.consume(token, plan())

    store.issue(plan("b" * 64))
