"""Domain errors.

The whole point of the lab is that one business rule produces two very
different shapes on the wire:

- REST answers with a status code and a small JSON error body.
- GraphQL answers with HTTP 200 and an ``errors`` array where every entry
  carries ``extensions.code``.

So the error itself lives here, with a stable ``code``, and each API layer
decides how to render it.
"""

from __future__ import annotations

from typing import Any


class DomainError(Exception):
    """Base class for every business rule failure."""

    code: str = "DOMAIN_ERROR"
    status_code: int = 400

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.details = details

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details:
            payload["details"] = self.details
        return payload

    def __repr__(self) -> str:
        return f"{type(self).__name__}(code={self.code!r}, message={self.message!r})"


class NotFoundError(DomainError):
    """The entity does not exist."""

    code = "NOT_FOUND"
    status_code = 404


class VersionConflictError(DomainError):
    """Optimistic concurrency check failed, someone else wrote first."""

    code = "VERSION_CONFLICT"
    status_code = 409


class RuleViolationError(DomainError):
    """The request is well formed but breaks a business rule."""

    code = "RULE_VIOLATION"
    status_code = 422


class IdempotencyMismatchError(DomainError):
    """The same idempotency key was replayed with a different payload."""

    code = "IDEMPOTENCY_MISMATCH"
    status_code = 400


class InvalidInputError(DomainError):
    """The request payload itself is not usable."""

    code = "BAD_USER_INPUT"
    status_code = 422


class ConflictError(DomainError):
    """Generic state conflict, for example an invoice that is already paid."""

    code = "CONFLICT"
    status_code = 409


class SandboxError(DomainError):
    """The code mode sandbox refused or failed to run the program."""

    code = "SANDBOX_ERROR"
    status_code = 400
