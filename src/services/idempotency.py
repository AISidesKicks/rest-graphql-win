"""Idempotency and optimistic concurrency helpers.

Both API styles use the same machinery here. The difference is only where the
key comes from: a header in REST, an argument in GraphQL.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Callable

from domain.clock import now_iso
from domain.errors import IdempotencyMismatchError, VersionConflictError


def request_hash(payload: Any) -> str:
    """A stable fingerprint of a request payload."""
    canonical = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def check_version(current: int, expected: int | None, entity: str, entity_id: int) -> None:
    """Raise when the caller's expected version does not match the stored one."""
    if expected is None:
        return
    if int(expected) != int(current):
        raise VersionConflictError(
            f"{entity} {entity_id} has version {current}, the request expected {expected}",
            entity=entity,
            id=entity_id,
            current_version=int(current),
            expected_version=int(expected),
        )


def replay_or_execute(
    repo,
    scope: str,
    key: str | None,
    payload: Any,
    action: Callable[[], dict[str, Any]],
) -> tuple[dict[str, Any], bool]:
    """Run an action once per idempotency key.

    Returns the result and a flag that says whether the result was a replay.
    A replay with a different payload is a mismatch, not a silent overwrite.
    """
    if not key:
        return action(), False

    fingerprint = request_hash(payload)
    existing = repo.get_idempotency(scope, key)
    if existing is not None:
        if existing["request_hash"] != fingerprint:
            raise IdempotencyMismatchError(
                f"idempotency key {key!r} was already used with a different payload",
                scope=scope,
                key=key,
            )
        return json.loads(existing["response_json"]), True

    result = action()
    repo.put_idempotency(scope, key, fingerprint, result, now_iso())
    return result, False
