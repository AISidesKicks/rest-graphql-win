"""Ticket rules: reading, creating, updating and closing."""

from __future__ import annotations

from typing import Any

from data.sqlite_repo import SqliteRepo
from domain.clock import now_iso
from domain.errors import NotFoundError, RuleViolationError
from domain.models import Page, Ticket, TicketMessage
from observability.tracing import span
from services.idempotency import check_version, replay_or_execute

CLOSABLE_STATUSES = {"open", "pending"}
OPEN_STATUSES = {"open", "pending"}
VALID_PRIORITIES = {"low", "normal", "high", "critical"}
VALID_CATEGORIES = {
    "billing",
    "bug",
    "how_to",
    "feature_request",
    "outage",
    "onboarding",
    "security",
}


class TicketsService:
    """Reads and writes on tickets."""

    def __init__(self, repo: SqliteRepo) -> None:
        self.repo = repo

    def list_tickets(
        self,
        account_id: int | None = None,
        status: str | None = None,
        priority: str | None = None,
        category: str | None = None,
        tag: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> Page[Ticket]:
        with span(
            "service.tickets.list",
            account_id=account_id,
            status=status,
            priority=priority,
            category=category,
            tag=tag,
            limit=limit,
        ):
            return self.repo.list_tickets(
                account_id=account_id,
                status=status,
                priority=priority,
                category=category,
                tag=tag,
                limit=limit,
                cursor=cursor,
            )

    def get_ticket(self, ticket_id: int) -> Ticket:
        ticket = self.repo.get_ticket(ticket_id)
        if ticket is None:
            raise NotFoundError(f"ticket {ticket_id} does not exist", ticket_id=ticket_id)
        return ticket

    def get_messages(self, ticket_id: int) -> list[TicketMessage]:
        self.get_ticket(ticket_id)
        return self.repo.list_ticket_messages(ticket_id)

    def get_tags(self, ticket_id: int) -> list[str]:
        self.get_ticket(ticket_id)
        return self.repo.list_ticket_tags(ticket_id)

    def get_tickets_for_accounts(self, account_ids: list[int]) -> dict[int, list[Ticket]]:
        return self.repo.list_tickets_by_account_ids(account_ids)

    def get_messages_for_tickets(self, ticket_ids: list[int]) -> dict[int, list[TicketMessage]]:
        return self.repo.list_ticket_messages_by_ticket_ids(ticket_ids)

    def get_tags_for_tickets(self, ticket_ids: list[int]) -> dict[int, list[str]]:
        return self.repo.list_ticket_tags_by_ticket_ids(ticket_ids)

    def create_ticket(
        self,
        account_id: int,
        subject: str,
        priority: str = "normal",
        category: str = "how_to",
        contact_id: int | None = None,
        agent_id: int | None = None,
        actor: str = "api",
    ) -> Ticket:
        if not subject or not subject.strip():
            raise RuleViolationError("the ticket needs a subject")
        if priority not in VALID_PRIORITIES:
            raise RuleViolationError(f"unknown priority {priority!r}", priority=priority)
        if category not in VALID_CATEGORIES:
            raise RuleViolationError(f"unknown category {category!r}", category=category)

        with span("service.tickets.create", account_id=account_id):
            with self.repo.transaction():
                account = self.repo.get_account(account_id)
                if account is None:
                    raise NotFoundError(
                        f"account {account_id} does not exist", account_id=account_id
                    )
                if account.status in {"suspended", "churned"}:
                    raise RuleViolationError(
                        f"account {account_id} is {account.status} and cannot open tickets",
                        account_id=account_id,
                        status=account.status,
                    )
                stamp = now_iso()
                ticket_id = self.repo.insert_ticket(
                    account_id=account_id,
                    contact_id=contact_id,
                    subject=subject.strip(),
                    status="open",
                    priority=priority,
                    category=category,
                    agent_id=agent_id,
                    created_at=stamp,
                    updated_at=stamp,
                )
                self.repo.insert_audit_event(
                    "ticket",
                    ticket_id,
                    "ticket.created",
                    actor,
                    {"account_id": account_id, "subject": subject.strip()},
                    stamp,
                )
            return self.get_ticket(ticket_id)

    def update_ticket(
        self,
        ticket_id: int,
        changes: dict[str, Any],
        expected_version: int | None = None,
        actor: str = "api",
    ) -> Ticket:
        allowed = {"subject", "priority", "category", "agent_id", "status"}
        unknown = set(changes) - allowed
        if unknown:
            raise RuleViolationError(
                f"ticket fields cannot be changed: {', '.join(sorted(unknown))}",
                fields=sorted(unknown),
            )
        if not changes:
            raise RuleViolationError("no ticket field was provided")
        if "priority" in changes and changes["priority"] not in VALID_PRIORITIES:
            raise RuleViolationError(f"unknown priority {changes['priority']!r}")
        if "category" in changes and changes["category"] not in VALID_CATEGORIES:
            raise RuleViolationError(f"unknown category {changes['category']!r}")
        if "status" in changes and changes["status"] not in {
            "open",
            "pending",
            "resolved",
            "closed",
        }:
            raise RuleViolationError(f"unknown status {changes['status']!r}")

        with span("service.tickets.update", ticket_id=ticket_id):
            with self.repo.transaction():
                ticket = self.get_ticket(ticket_id)
                check_version(ticket.version, expected_version, "ticket", ticket_id)
                fields = dict(changes)
                fields["updated_at"] = now_iso()
                if not self.repo.update_ticket(ticket_id, ticket.version, fields):
                    raise RuleViolationError(
                        "the ticket was modified while the request was running",
                        ticket_id=ticket_id,
                    )
                self.repo.insert_audit_event(
                    "ticket", ticket_id, "ticket.updated", actor, {"changes": changes}, now_iso()
                )
            return self.get_ticket(ticket_id)

    def add_message(
        self,
        ticket_id: int,
        body: str,
        author_type: str = "customer",
        author_id: int | None = None,
        actor: str = "api",
    ) -> TicketMessage:
        if not body or not body.strip():
            raise RuleViolationError("the message needs a body")
        if author_type not in {"customer", "agent", "system"}:
            raise RuleViolationError(f"unknown author type {author_type!r}")

        with span("service.tickets.add_message", ticket_id=ticket_id):
            with self.repo.transaction():
                ticket = self.get_ticket(ticket_id)
                stamp = now_iso()
                message_id = self.repo.insert_ticket_message(
                    ticket_id, author_type, author_id, body.strip(), stamp
                )
                fields: dict[str, Any] = {"updated_at": stamp}
                if ticket.first_response_at is None and author_type == "agent":
                    fields["first_response_at"] = stamp
                self.repo.update_ticket(ticket_id, ticket.version, fields)
                self.repo.insert_audit_event(
                    "ticket",
                    ticket_id,
                    "ticket.message_added",
                    actor,
                    {"author_type": author_type},
                    stamp,
                )
            messages = self.repo.list_ticket_messages(ticket_id)
            for message in messages:
                if message.id == message_id:
                    return message
            raise RuleViolationError("the message was not stored", ticket_id=ticket_id)

    def close_ticket(
        self,
        ticket_id: int,
        expected_version: int | None = None,
        idempotency_key: str | None = None,
        actor: str = "api",
    ) -> dict[str, Any]:
        """Close a ticket.

        Closing twice with the same idempotency key replays the first answer.
        Closing twice without a key is a rule violation, because the client
        should have sent a key if it wanted a safe retry.
        """
        with span("service.tickets.close", ticket_id=ticket_id):
            with self.repo.transaction():
                ticket = self.get_ticket(ticket_id)
                stamp = now_iso()

                def action() -> dict[str, Any]:
                    if ticket.status not in CLOSABLE_STATUSES:
                        raise RuleViolationError(
                            f"ticket {ticket_id} is {ticket.status} and cannot be closed",
                            ticket_id=ticket_id,
                            status=ticket.status,
                        )
                    check_version(ticket.version, expected_version, "ticket", ticket_id)
                    fields = {
                        "status": "closed",
                        "resolved_at": stamp,
                        "updated_at": stamp,
                    }
                    if not self.repo.update_ticket(ticket_id, ticket.version, fields):
                        raise RuleViolationError(
                            "the ticket was modified while the request was running",
                            ticket_id=ticket_id,
                        )
                    self.repo.insert_audit_event(
                        "ticket", ticket_id, "ticket.closed", actor, {}, stamp
                    )
                    closed = self.get_ticket(ticket_id)
                    return {
                        "ticket_id": closed.id,
                        "status": closed.status,
                        "version": closed.version,
                        "resolved_at": closed.resolved_at,
                    }

                result, replayed = replay_or_execute(
                    self.repo,
                    scope="tickets.close",
                    key=idempotency_key,
                    payload={"ticket_id": ticket_id},
                    action=action,
                )
            result = dict(result)
            result["replayed"] = replayed
            return result
