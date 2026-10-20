"""Pydantic schemas for the REST surface.

The shapes are intentionally close to the domain objects, so the REST and the
GraphQL response bodies can be compared field by field.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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


class AccountPage(BaseModel):
    items: list[AccountOut]
    next_cursor: str | None = None


class AccountUpdate(BaseModel):
    name: str | None = None
    status: str | None = None
    seat_limit: int | None = None
    segment: str | None = None
    country: str | None = None
    version: int | None = Field(
        default=None,
        description="expected version, the If-Match header does the same job",
    )


class ContactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    account_id: int
    email: str
    name: str
    role: str
    is_primary: bool


class TicketOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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


class TicketPage(BaseModel):
    items: list[TicketOut]
    next_cursor: str | None = None


class TicketCreate(BaseModel):
    account_id: int
    subject: str
    priority: str = "normal"
    category: str = "how_to"
    contact_id: int | None = None
    agent_id: int | None = None


class TicketUpdate(BaseModel):
    subject: str | None = None
    priority: str | None = None
    category: str | None = None
    status: str | None = None
    agent_id: int | None = None
    version: int | None = None


class TicketMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ticket_id: int
    author_type: str
    author_id: int | None
    body: str
    created_at: str


class TicketMessageCreate(BaseModel):
    body: str
    author_type: str = "customer"
    author_id: int | None = None


class TicketCloseOut(BaseModel):
    ticket_id: int
    status: str
    version: int
    resolved_at: str | None
    replayed: bool = False


class SubscriptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    account_id: int
    plan_id: int
    status: str
    seats: int
    started_at: str
    renews_at: str
    cancelled_at: str | None
    version: int


class ChangePlanRequest(BaseModel):
    new_plan_code: str
    seats: int | None = None
    version: int | None = None


class ChangePlanOut(BaseModel):
    subscription_id: int
    account_id: int
    from_plan: str
    to_plan: str
    seats: int
    delta_cents: int
    invoice_id: int
    version: int
    changed_at: str
    replayed: bool = False


class InvoiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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


class InvoicePage(BaseModel):
    items: list[InvoiceOut]
    next_cursor: str | None = None


class InvoiceLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    invoice_id: int
    description: str
    quantity: int
    unit_price_cents: int
    amount_cents: int
    period_start: str
    period_end: str


class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    invoice_id: int
    amount_cents: int
    method: str
    status: str
    paid_at: str | None
    reference: str | None


class PaymentCreate(BaseModel):
    amount_cents: int
    method: str = "card"


class PaymentResultOut(BaseModel):
    payment_id: int
    invoice_id: int
    amount_cents: int
    method: str
    invoice_status: str
    total_paid_cents: int
    invoice_version: int
    paid_at: str | None
    replayed: bool = False


class AgentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    team: str
    active: bool


class KbArticleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    slug: str
    category: str
    body: str
    updated_at: str


class PlanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    monthly_price_cents: int
    included_tickets: int
    overage_cents: int
    sla_hours: int


class SqlRowsOut(BaseModel):
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int


class SqlQueryIn(BaseModel):
    sql: str
    params: list[Any] = Field(default_factory=list)
    row_cap: int = 1_000


class AnalyticsQueryOut(BaseModel):
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
