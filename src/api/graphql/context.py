"""The GraphQL request context.

The context carries the services, the batch loaders and one switch that turns
the batch loader off. The lab uses that switch to show the N+1 trap next to the
batched version of the same query.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from strawberry.fastapi import BaseContext

from api.graphql.loaders import Loaders
from services import Services

BATCH_HEADER = "x-lab-batch"


@dataclass
class GraphQLContext(BaseContext):
    services: Services
    batch_enabled: bool = True
    loaders: Loaders = field(init=False)

    def __post_init__(self) -> None:
        self.loaders = Loaders(self.services)


def build_context(request: Any, services: Services) -> GraphQLContext:
    """Build the context, reading the batch switch from the request headers."""
    header = request.headers.get(BATCH_HEADER)
    enabled = True
    if header is not None:
        enabled = header.strip().lower() not in {"0", "off", "false", "no"}
    return GraphQLContext(services=services, batch_enabled=enabled)
