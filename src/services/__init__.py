"""The service layer.

Every business rule of the lab lives here. The REST routers and the GraphQL
resolvers only shape the response, so a measured difference between the two API
styles comes from the transport and the query shape, never from duplicated
logic.
"""

from __future__ import annotations

from dataclasses import dataclass

from data.duckdb_repo import DuckDbRepo
from data.sqlite_repo import SqliteRepo
from services.accounts import AccountsService
from services.analytics import AnalyticsService
from services.invoices import InvoicesService
from services.subscriptions import SubscriptionsService
from services.tickets import TicketsService


@dataclass
class Services:
    """All services, wired to the two databases."""

    repo: SqliteRepo
    duck: DuckDbRepo

    def __post_init__(self) -> None:
        self.accounts = AccountsService(self.repo)
        self.tickets = TicketsService(self.repo)
        self.subscriptions = SubscriptionsService(self.repo)
        self.invoices = InvoicesService(self.repo)
        self.analytics = AnalyticsService(self.duck, self.repo)

    def close(self) -> None:
        self.repo.close()
        self.duck.close()


__all__ = [
    "Services",
    "AccountsService",
    "AnalyticsService",
    "InvoicesService",
    "SubscriptionsService",
    "TicketsService",
]
