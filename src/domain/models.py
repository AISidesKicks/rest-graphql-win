"""Domain entities.

Plain dataclasses so the service layer can hand the same objects to the REST
serializers and to the GraphQL types. Every mutable entity carries a
``version`` field, that is the optimistic concurrency token.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class AccountStatus(StrEnum):
    ACTIVE = "active"
    TRIAL = "trial"
    PAST_DUE = "past_due"
    SUSPENDED = "suspended"
    CHURNED = "churned"


class SubscriptionStatus(StrEnum):
    ACTIVE = "active"
    TRIAL = "trial"
    PAST_DUE = "past_due"
    CANCELLED = "cancelled"


class TicketStatus(StrEnum):
    OPEN = "open"
    PENDING = "pending"
    RESOLVED = "resolved"
    CLOSED = "closed"


class TicketPriority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class InvoiceStatus(StrEnum):
    DRAFT = "draft"
    OPEN = "open"
    PAID = "paid"
    OVERDUE = "overdue"
    VOID = "void"


class PaymentStatus(StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class AuthorType(StrEnum):
    CUSTOMER = "customer"
    AGENT = "agent"
    SYSTEM = "system"


@dataclass(frozen=True)
class Plan:
    id: int
    code: str
    name: str
    monthly_price_cents: int
    included_tickets: int
    overage_cents: int
    sla_hours: int


@dataclass(frozen=True)
class Account:
    id: int
    name: str
    slug: str
    plan_id: int
    status: str
    seat_limit: int
    country: str
    segment: str
    created_at: str
    version: int


@dataclass(frozen=True)
class Contact:
    id: int
    account_id: int
    email: str
    name: str
    role: str
    is_primary: bool


@dataclass(frozen=True)
class Subscription:
    id: int
    account_id: int
    plan_id: int
    status: str
    seats: int
    started_at: str
    renews_at: str
    cancelled_at: str | None
    version: int


@dataclass(frozen=True)
class Ticket:
    id: int
    account_id: int
    contact_id: int | None
    subject: str
    status: str
    priority: str
    category: str
    agent_id: int | None
    created_at: str
    updated_at: str
    first_response_at: str | None
    resolved_at: str | None
    version: int


@dataclass(frozen=True)
class TicketMessage:
    id: int
    ticket_id: int
    author_type: str
    author_id: int | None
    body: str
    created_at: str


@dataclass(frozen=True)
class Agent:
    id: int
    name: str
    email: str
    team: str
    active: bool


@dataclass(frozen=True)
class KbArticle:
    id: int
    title: str
    slug: str
    category: str
    body: str
    updated_at: str


@dataclass(frozen=True)
class Invoice:
    id: int
    account_id: int
    subscription_id: int | None
    number: str
    status: str
    issued_at: str
    due_at: str
    paid_at: str | None
    subtotal_cents: int
    tax_cents: int
    total_cents: int
    version: int


@dataclass(frozen=True)
class InvoiceLine:
    id: int
    invoice_id: int
    description: str
    quantity: int
    unit_price_cents: int
    amount_cents: int
    period_start: str
    period_end: str


@dataclass(frozen=True)
class Payment:
    id: int
    invoice_id: int
    amount_cents: int
    method: str
    status: str
    paid_at: str | None
    reference: str | None


@dataclass(frozen=True)
class AuditEvent:
    id: int
    entity_type: str
    entity_id: int
    kind: str
    actor: str
    payload_json: str
    created_at: str


@dataclass(frozen=True)
class Page[T]:
    """A keyset paginated slice of results."""

    items: list[T]
    next_cursor: str | None
    total: int | None = None

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"items": self.items, "next_cursor": self.next_cursor}
        if self.total is not None:
            payload["total"] = self.total
        return payload
