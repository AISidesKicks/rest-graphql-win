"""A small DataLoader style batch loader.

Without it, a GraphQL query over a list of accounts issues one SQL query per
account. The lab shows both variants, so the difference has to be measurable.

The loader collects the keys asked for during one tick and resolves them with
a single call into the service layer.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Generic, Hashable, TypeVar

K = TypeVar("K", bound=Hashable)
V = TypeVar("V")


class BatchLoader(Generic[K, V]):
    """Resolve many keys with one call, and cache the answers."""

    def __init__(self, load: Callable[[list[K]], list[V]]) -> None:
        self._load = load
        self._cache: dict[K, V] = {}
        self._pending: dict[K, asyncio.Future] = {}
        self._task: asyncio.Task | None = None

    async def load(self, key: K) -> V:
        if key in self._cache:
            return self._cache[key]
        if key not in self._pending:
            self._pending[key] = asyncio.get_running_loop().create_future()
            if self._task is None:
                self._task = asyncio.create_task(self._dispatch())
        return await self._pending[key]

    async def load_many(self, keys: list[K]) -> list[V]:
        return list(await asyncio.gather(*(self.load(key) for key in keys)))

    async def _dispatch(self) -> None:
        await asyncio.sleep(0)
        keys = list(self._pending)
        pending = self._pending
        self._pending = {}
        self._task = None
        try:
            results = await asyncio.to_thread(self._load, keys)
        except Exception as exc:
            for future in pending.values():
                if not future.done():
                    future.set_exception(exc)
            return
        for key, result in zip(keys, results):
            if not pending[key].done():
                pending[key].set_result(result)

    def prime(self, key: K, value: V) -> None:
        self._cache[key] = value

    def clear(self) -> None:
        self._cache.clear()


class Loaders:
    """Every batch loader the schema needs, one per fan out point."""

    def __init__(self, services: Any) -> None:
        repo = services.repo

        self.plans_by_id: BatchLoader[int, Any] = BatchLoader(
            lambda keys: [repo.get_plan(key) for key in keys]
        )
        self.agents_by_id: BatchLoader[int, Any] = BatchLoader(
            lambda keys: [repo.get_agent(key) for key in keys]
        )
        self.accounts_by_id: BatchLoader[int, Any] = BatchLoader(
            lambda keys: [repo.get_account(key) for key in keys]
        )
        self.contacts_by_account: BatchLoader[int, list[Any]] = BatchLoader(
            lambda keys: [repo.list_contacts(key) for key in keys]
        )
        self.tickets_by_account: BatchLoader[int, list[Any]] = BatchLoader(
            lambda keys: _group(repo.list_tickets_by_account_ids(keys), keys)
        )
        self.messages_by_ticket: BatchLoader[int, list[Any]] = BatchLoader(
            lambda keys: _group(repo.list_ticket_messages_by_ticket_ids(keys), keys)
        )
        self.tags_by_ticket: BatchLoader[int, list[str]] = BatchLoader(
            lambda keys: _group(repo.list_ticket_tags_by_ticket_ids(keys), keys)
        )
        self.invoices_by_account: BatchLoader[int, list[Any]] = BatchLoader(
            lambda keys: _group(_invoices_by_account(repo, keys), keys)
        )
        self.lines_by_invoice: BatchLoader[int, list[Any]] = BatchLoader(
            lambda keys: [repo.list_invoice_lines(key) for key in keys]
        )
        self.payments_by_invoice: BatchLoader[int, list[Any]] = BatchLoader(
            lambda keys: [repo.list_payments(key) for key in keys]
        )
        self.subscriptions_by_account: BatchLoader[int, Any] = BatchLoader(
            lambda keys: [
                (repo.list_subscriptions(key)[0] if repo.list_subscriptions(key) else None)
                for key in keys
            ]
        )


def _group(mapping: dict[Any, list[Any]], keys: list[Any]) -> list[list[Any]]:
    return [mapping.get(key, []) for key in keys]


def _invoices_by_account(repo: Any, keys: list[int]) -> dict[int, list[Any]]:
    grouped: dict[int, list[Any]] = {}
    for key in keys:
        page = repo.list_invoices(account_id=key, limit=500)
        grouped[key] = list(page.items)
    return grouped
