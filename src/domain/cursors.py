"""Cursor helpers for keyset pagination.

Both API styles use the same cursors, so a REST page and a GraphQL page can be
compared row for row.
"""

from __future__ import annotations

import base64
import json
from typing import Any

from .errors import InvalidInputError


def encode_cursor(values: list[Any]) -> str:
    """Encode the keyset values of the last row into an opaque cursor."""
    raw = json.dumps(values, separators=(",", ":"), default=str).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(cursor: str | None) -> list[Any] | None:
    """Decode a cursor back into keyset values, or None when there is none."""
    if cursor is None or cursor == "":
        return None
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        decoded = base64.urlsafe_b64decode(padded.encode("ascii"))
        values = json.loads(decoded.decode("utf-8"))
    except Exception as exc:
        raise InvalidInputError(f"cursor is not readable: {cursor!r}") from exc
    if not isinstance(values, list):
        raise InvalidInputError(f"cursor does not hold a keyset: {cursor!r}")
    return values
