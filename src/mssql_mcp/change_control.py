"""Short-lived, one-time approvals for state-changing SQL."""

from __future__ import annotations

import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import Lock

from mssql_mcp.security import ChangePlan, SecurityValidationError


@dataclass(frozen=True, slots=True)
class Approval:
    operation: str
    query_sha256: str
    expires_monotonic: float


class ChangeApprovalStore:
    """Stores bounded one-time approvals without retaining SQL text."""

    def __init__(
        self,
        ttl_seconds: int,
        max_pending: int,
        *,
        monotonic_clock: Callable[[], float] = time.monotonic,
        utc_clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_pending = max_pending
        self._monotonic_clock = monotonic_clock
        self._utc_clock = utc_clock or (lambda: datetime.now(UTC))
        self._approvals: dict[str, Approval] = {}
        self._lock = Lock()

    def issue(self, plan: ChangePlan) -> tuple[str, str]:
        now = self._monotonic_clock()
        with self._lock:
            self._remove_expired(now)
            if len(self._approvals) >= self.max_pending:
                raise SecurityValidationError(
                    "Too many pending SQL changes; wait for approvals to expire or execute one"
                )
            token = secrets.token_urlsafe(32)
            self._approvals[token] = Approval(
                operation=plan.operation,
                query_sha256=plan.query_sha256,
                expires_monotonic=now + self.ttl_seconds,
            )

        expires_at = self._utc_clock() + timedelta(seconds=self.ttl_seconds)
        return token, expires_at.isoformat()

    def consume(self, token: str, plan: ChangePlan) -> None:
        if not isinstance(token, str) or not token.strip():
            raise SecurityValidationError("A confirmation token is required")

        now = self._monotonic_clock()
        with self._lock:
            self._remove_expired(now)
            approval = self._approvals.pop(token, None)

        if approval is None:
            raise SecurityValidationError("Confirmation token is invalid, expired, or already used")
        if approval.operation != plan.operation or not secrets.compare_digest(
            approval.query_sha256, plan.query_sha256
        ):
            raise SecurityValidationError(
                "Confirmation token does not match the exact prepared SQL statement"
            )

    def _remove_expired(self, now: float) -> None:
        expired = [
            token
            for token, approval in self._approvals.items()
            if approval.expires_monotonic <= now
        ]
        for token in expired:
            self._approvals.pop(token, None)
