"""Stable response envelopes returned by MCP tools."""

from __future__ import annotations

from typing import Any


def success_response(
    data: Any,
    *,
    row_count: int | None = None,
    **metadata: Any,
) -> dict[str, Any]:
    if row_count is None:
        row_count = len(data) if isinstance(data, list) else 1
    return {
        "success": True,
        "data": data,
        "row_count": row_count,
        "error": None,
        "metadata": metadata,
    }


def error_response(error: str, *, data: Any) -> dict[str, Any]:
    return {
        "success": False,
        "data": data,
        "row_count": 0,
        "error": error,
        "metadata": {},
    }
