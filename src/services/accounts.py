"""Account rules."""

from __future__ import annotations

from typing import Any, Iterable

from data.sqlite_repo import SqliteRepo
from domain.clock import now_iso
from domain.errors import NotFoundError, RuleViolationError
from domain.models import Account, Contact, Page
from observability.tracing import span
from services.idempotency import check_version


class AccountsService:
    """Reads and writes on accounts."""

    def __init__(self, repo: SqliteRepo) -> None:
        self.repo = repo

    def list_accounts(
        self,
        status: str | None = None,
        plan: str | None = None,
        segment: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> Page[Account]:
        with span("service.accounts.list", status=status, plan=plan, segment=segment, limit=limit):
            return self.repo.list_accounts(
                status=status, plan=plan, segment=segment, limit=limit, cursor=cursor
            )

    def get_account(self, account_id: int) -> Account:
        account = self.repo.get_account(account_id)
        if account is None:
            raise NotFoundError(f"account {account_id} does not exist", account_id=account_id)
        return account

    def get_accounts(self, account_ids: Iterable[int]) -> dict[int, Account]:
        return {account.id: account for account in self.repo.list_accounts_by_ids(list(account_ids))}

    def get_contacts(self, account_id: int) -> list[Contact]:
        self.get_account(account_id)
        return self.repo.list_contacts(account_id)

    def get_contacts_for_accounts(self, account_ids: Iterable[int]) -> dict[int, list[Contact]]:
        return self.repo.list_contacts_by_account_ids(list(account_ids))

    def update_account(
        self,
        account_id: int,
        changes: dict[str, Any],
        expected_version: int | None = None,
        actor: str = "api",
    ) -> Account:
        allowed = {"name", "status", "seat_limit", "segment", "country"}
        unknown = set(changes) - allowed
        if unknown:
            raise RuleViolationError(
                f"account fields cannot be changed: {', '.join(sorted(unknown))}",
                fields=sorted(unknown),
            )
        if not changes:
            raise RuleViolationError("no account field was provided")

        with span("service.accounts.update", account_id=account_id):
            with self.repo.transaction():
                account = self.get_account(account_id)
                check_version(account.version, expected_version, "account", account_id)
                if "status" in changes and changes["status"] not in {
                    "active",
                    "trial",
                    "past_due",
                    "suspended",
                    "churned",
                }:
                    raise RuleViolationError(
                        f"unknown account status {changes['status']!r}", status=changes["status"]
                    )
                if not self.repo.update_account(account_id, account.version, changes):
                    raise RuleViolationError(
                        "the account was modified while the request was running",
                        account_id=account_id,
                    )
                self.repo.insert_audit_event(
                    "account",
                    account_id,
                    "account.updated",
                    actor,
                    {"changes": changes},
                    now_iso(),
                )
            return self.get_account(account_id)

    def audit_trail(self, account_id: int, limit: int = 50) -> list[dict[str, Any]]:
        return [
            {
                "id": event.id,
                "kind": event.kind,
                "actor": event.actor,
                "payload": event.payload_json,
                "created_at": event.created_at,
            }
            for event in self.repo.list_audit_events("account", account_id, limit)
        ]
