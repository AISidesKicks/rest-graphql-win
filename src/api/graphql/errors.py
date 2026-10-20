"""GraphQL error mapping.

The service layer raises one error type. GraphQL renders it inside the
``errors`` array with a stable ``extensions.code``, while REST renders it as a
status code plus a small body. The rule is the same, the shape is not.
"""

from __future__ import annotations

from typing import Any, Callable, TypeVar

from graphql import GraphQLError

from domain.errors import DomainError

T = TypeVar("T")


def to_graphql_error(exc: DomainError) -> GraphQLError:
    """Turn a domain error into a GraphQL error with extensions."""
    extensions: dict[str, Any] = {"code": exc.code}
    if exc.details:
        extensions["details"] = exc.details
    return GraphQLError(exc.message, extensions=extensions)


def map_errors(action: Callable[[], T]) -> T:
    """Run a service call and translate domain errors."""
    try:
        return action()
    except DomainError as exc:
        raise to_graphql_error(exc) from exc
