"""Strawberry types, enums and input objects for the GraphQL surface.

The GraphQL schema is intentionally shaped like the REST one, so a reader can
hold both in their head at the same time. The differences that matter are the
ones the lab teaches: enums validate at the schema level, nested fields resolve
through the batch loader, and errors travel inside the payload.
"""

from __future__ import annotations

from enum import Enum

import strawberry
from strawberry.scalars import JSON

from domain import models as domain


@strawberry.enum(name="AccountStatus", description="The lifecycle state of an account")
class AccountStatusGQL(Enum):
    ACTIVE = "active"
    TRIAL = "trial"
    PAST_DUE = "past_due"
    SUSPENDED = "suspended"
    CHURNED = "churned"


@strawberry.enum(name="SubscriptionStatus", description="The lifecycle state of a subscription")
class SubscriptionStatusGQL(Enum):
    ACTIVE = "active"
    TRIAL = "trial"
    PAST_DUE = "past_due"
    CANCELLED = "cancelled"


@strawberry.enum(name="TicketStatus", description="The lifecycle state of a ticket")
class TicketStatusGQL(Enum):
    OPEN = "open"
    PENDING = "pending"
    RESOLVED = "resolved"
    CLOSED = "closed"


@strawberry.enum(name="TicketPriority", description="How urgent a ticket is")
class TicketPriorityGQL(Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


@strawberry.enum(name="InvoiceStatus", description="The payment state of an invoice")
class InvoiceStatusGQL(Enum):
    DRAFT = "draft"
    OPEN = "open"
    PAID = "paid"
    OVERDUE = "overdue"
    VOID = "void"


@strawberry.enum(name="AuthorType", description="Who wrote a ticket message")
class AuthorTypeGQL(Enum):
    CUSTOMER = "customer"
    AGENT = "agent"
    SYSTEM = "system"


@strawberry.type
class Plan:
    id: int
    code: str
    name: str
    monthly_price_cents: int
    included_tickets: int
    overage_cents: int
    sla_hours: int


@strawberry.type
class Contact:
    id: int
    account_id: int
    email: str
    name: str
    role: str
    is_primary: bool


@strawberry.type
class Agent:
    id: int
    name: str
    email: str
    team: str
    active: bool


@strawberry.type
class KbArticle:
    id: int
    title: str
    slug: str
    category: str
    body: str
    updated_at: str


@strawberry.type
class TicketMessage:
    id: int
    ticket_id: int
    author_type: str
    author_id: int | None
    body: str
    created_at: str


@strawberry.type
class InvoiceLine:
    id: int
    invoice_id: int
    description: str
    quantity: int
    unit_price_cents: int
    amount_cents: int
    period_start: str
    period_end: str


@strawberry.type
class Payment:
    id: int
    invoice_id: int
    amount_cents: int
    method: str
    status: str
    paid_at: str | None
    reference: str | None


@strawberry.type
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

    @strawberry.field(description="The agent that owns the ticket")
    async def agent(self, info: strawberry.Info) -> Agent | None:
        context = info.context
        if self.agent_id is None:
            return None
        if not context.batch_enabled:
            agent = context.services.repo.get_agent(self.agent_id)
            return None if agent is None else _agent(agent)
        agent = await context.loaders.agents_by_id.load(self.agent_id)
        return None if agent is None else _agent(agent)

    @strawberry.field(description="Every message on the ticket")
    async def messages(self, info: strawberry.Info) -> list[TicketMessage]:
        context = info.context
        if not context.batch_enabled:
            messages = context.services.repo.list_ticket_messages(self.id)
        else:
            messages = await context.loaders.messages_by_ticket.load(self.id)
        return [_message(message) for message in messages]

    @strawberry.field(description="The tags on the ticket")
    async def tags(self, info: strawberry.Info) -> list[str]:
        context = info.context
        if not context.batch_enabled:
            return context.services.repo.list_ticket_tags(self.id)
        return await context.loaders.tags_by_ticket.load(self.id)

    @strawberry.field(description="The account the ticket belongs to")
    async def account(self, info: strawberry.Info) -> Account | None:
        context = info.context
        if not context.batch_enabled:
            account = context.services.repo.get_account(self.account_id)
            return None if account is None else _account(account)
        account = await context.loaders.accounts_by_id.load(self.account_id)
        return None if account is None else _account(account)


@strawberry.type
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

    @strawberry.field(description="The lines of the invoice")
    async def lines(self, info: strawberry.Info) -> list[InvoiceLine]:
        context = info.context
        if not context.batch_enabled:
            lines = context.services.repo.list_invoice_lines(self.id)
        else:
            lines = await context.loaders.lines_by_invoice.load(self.id)
        return [_line(line) for line in lines]

    @strawberry.field(description="The payments recorded against the invoice")
    async def payments(self, info: strawberry.Info) -> list[Payment]:
        context = info.context
        if not context.batch_enabled:
            payments = context.services.repo.list_payments(self.id)
        else:
            payments = await context.loaders.payments_by_invoice.load(self.id)
        return [_payment(payment) for payment in payments]


@strawberry.type
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

    @strawberry.field(description="The plan of the subscription")
    async def plan(self, info: strawberry.Info) -> Plan | None:
        context = info.context
        if not context.batch_enabled:
            plan = context.services.repo.get_plan(self.plan_id)
            return None if plan is None else _plan(plan)
        plan = await context.loaders.plans_by_id.load(self.plan_id)
        return None if plan is None else _plan(plan)


@strawberry.type
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

    @strawberry.field(description="The plan of the account")
    async def plan(self, info: strawberry.Info) -> Plan | None:
        context = info.context
        if not context.batch_enabled:
            plan = context.services.repo.get_plan(self.plan_id)
            return None if plan is None else _plan(plan)
        plan = await context.loaders.plans_by_id.load(self.plan_id)
        return None if plan is None else _plan(plan)

    @strawberry.field(description="The contacts of the account")
    async def contacts(self, info: strawberry.Info) -> list[Contact]:
        context = info.context
        if not context.batch_enabled:
            contacts = context.services.repo.list_contacts(self.id)
        else:
            contacts = await context.loaders.contacts_by_account.load(self.id)
        return [_contact(contact) for contact in contacts]

    @strawberry.field(description="The tickets of the account")
    async def tickets(
        self,
        info: strawberry.Info,
        status: TicketStatusGQL | None = None,
        priority: TicketPriorityGQL | None = None,
        limit: int = 10,
    ) -> list[Ticket]:
        context = info.context
        status_value = status.value if status else None
        priority_value = priority.value if priority else None
        if not context.batch_enabled:
            page = context.services.repo.list_tickets(
                account_id=self.id, status=status_value, priority=priority_value, limit=limit
            )
            tickets = page.items
        else:
            tickets = await context.loaders.tickets_by_account.load(self.id)
            if status_value:
                tickets = [t for t in tickets if t.status == status_value]
            if priority_value:
                tickets = [t for t in tickets if t.priority == priority_value]
            tickets = tickets[:limit]
        return [_ticket(ticket) for ticket in tickets]

    @strawberry.field(description="The invoices of the account")
    async def invoices(
        self, info: strawberry.Info, status: InvoiceStatusGQL | None = None, limit: int = 10
    ) -> list[Invoice]:
        context = info.context
        status_value = status.value if status else None
        if not context.batch_enabled:
            page = context.services.repo.list_invoices(
                account_id=self.id, status=status_value, limit=limit
            )
            invoices = list(page.items)
        else:
            invoices = await context.loaders.invoices_by_account.load(self.id)
            if status_value:
                invoices = [i for i in invoices if i.status == status_value]
            invoices = invoices[:limit]
        return [_invoice(invoice) for invoice in invoices]

    @strawberry.field(description="The subscription of the account")
    async def subscription(self, info: strawberry.Info) -> Subscription | None:
        context = info.context
        if not context.batch_enabled:
            subscriptions = context.services.repo.list_subscriptions(self.id)
            subscription = subscriptions[0] if subscriptions else None
        else:
            subscription = await context.loaders.subscriptions_by_account.load(self.id)
        return None if subscription is None else _subscription(subscription)


@strawberry.type
class AccountPage:
    items: list[Account]
    next_cursor: str | None


@strawberry.type
class TicketPage:
    items: list[Ticket]
    next_cursor: str | None


@strawberry.type
class InvoicePage:
    items: list[Invoice]
    next_cursor: str | None


@strawberry.type
class SqlResult:
    columns: list[str]
    rows: list[JSON]
    row_count: int


@strawberry.type
class RevenueByPlanRow:
    period: str
    plan_code: str
    revenue_cents: int
    invoices: int


@strawberry.type
class UsageTrendRow:
    date: str
    account_id: int
    total: float


@strawberry.type
class TicketAtRiskRow:
    account_id: int
    account_name: str
    plan_code: str
    segment: str
    overdue_cents: int
    overdue_invoices: int
    critical_open: int
    revenue_at_risk_cents: int


@strawberry.type
class TopAgentRow:
    agent_id: int
    agent_name: str
    team: str
    tickets: int
    avg_response_seconds: float | None


@strawberry.input
class CreateTicketInput:
    account_id: int
    subject: str
    priority: TicketPriorityGQL = TicketPriorityGQL.NORMAL
    category: str = "how_to"
    contact_id: int | None = None
    agent_id: int | None = None


@strawberry.input
class UpdateTicketInput:
    subject: str | None = None
    priority: TicketPriorityGQL | None = None
    category: str | None = None
    status: TicketStatusGQL | None = None
    agent_id: int | None = None


@strawberry.input
class UpdateAccountInput:
    name: str | None = None
    status: AccountStatusGQL | None = None
    seat_limit: int | None = None
    segment: str | None = None
    country: str | None = None


@strawberry.type
class CloseTicketPayload:
    ticket_id: int
    status: str
    version: int
    resolved_at: str | None
    replayed: bool


@strawberry.type
class ChangePlanPayload:
    subscription_id: int
    account_id: int
    from_plan: str
    to_plan: str
    seats: int
    delta_cents: int
    invoice_id: int
    version: int
    changed_at: str
    replayed: bool


@strawberry.type
class RecordPaymentPayload:
    payment_id: int
    invoice_id: int
    amount_cents: int
    method: str
    invoice_status: str
    total_paid_cents: int
    invoice_version: int
    paid_at: str | None
    replayed: bool


@strawberry.type
class PartialFailureDemo:
    """Shows how GraphQL handles a field that fails.

    ``required`` is non nullable, so a failure bubbles up and nulls the parent.
    ``optional`` is nullable, so a failure only nulls itself.
    """

    fail_required: bool = False
    fail_optional: bool = False

    @strawberry.field
    def required(self) -> str:
        if self.fail_required:
            raise DemoFailure("the required field failed on purpose")
        return "the required field worked"

    @strawberry.field
    def optional(self) -> str | None:
        if self.fail_optional:
            raise DemoFailure("the optional field failed on purpose")
        return "the optional field worked"


class DemoFailure(Exception):
    """Raised by the partial failure demo."""


def _plan(plan: domain.Plan) -> Plan:
    return Plan(
        id=plan.id,
        code=plan.code,
        name=plan.name,
        monthly_price_cents=plan.monthly_price_cents,
        included_tickets=plan.included_tickets,
        overage_cents=plan.overage_cents,
        sla_hours=plan.sla_hours,
    )


def _contact(contact: domain.Contact) -> Contact:
    return Contact(
        id=contact.id,
        account_id=contact.account_id,
        email=contact.email,
        name=contact.name,
        role=contact.role,
        is_primary=contact.is_primary,
    )


def _agent(agent: domain.Agent) -> Agent:
    return Agent(
        id=agent.id,
        name=agent.name,
        email=agent.email,
        team=agent.team,
        active=agent.active,
    )


def _article(article: domain.KbArticle) -> KbArticle:
    return KbArticle(
        id=article.id,
        title=article.title,
        slug=article.slug,
        category=article.category,
        body=article.body,
        updated_at=article.updated_at,
    )


def _ticket(ticket: domain.Ticket) -> Ticket:
    return Ticket(
        id=ticket.id,
        account_id=ticket.account_id,
        contact_id=ticket.contact_id,
        subject=ticket.subject,
        status=ticket.status,
        priority=ticket.priority,
        category=ticket.category,
        agent_id=ticket.agent_id,
        created_at=ticket.created_at,
        updated_at=ticket.updated_at,
        first_response_at=ticket.first_response_at,
        resolved_at=ticket.resolved_at,
        version=ticket.version,
    )


def _message(message: domain.TicketMessage) -> TicketMessage:
    return TicketMessage(
        id=message.id,
        ticket_id=message.ticket_id,
        author_type=message.author_type,
        author_id=message.author_id,
        body=message.body,
        created_at=message.created_at,
    )


def _invoice(invoice: domain.Invoice) -> Invoice:
    return Invoice(
        id=invoice.id,
        account_id=invoice.account_id,
        subscription_id=invoice.subscription_id,
        number=invoice.number,
        status=invoice.status,
        issued_at=invoice.issued_at,
        due_at=invoice.due_at,
        paid_at=invoice.paid_at,
        subtotal_cents=invoice.subtotal_cents,
        tax_cents=invoice.tax_cents,
        total_cents=invoice.total_cents,
        version=invoice.version,
    )


def _line(line: domain.InvoiceLine) -> InvoiceLine:
    return InvoiceLine(
        id=line.id,
        invoice_id=line.invoice_id,
        description=line.description,
        quantity=line.quantity,
        unit_price_cents=line.unit_price_cents,
        amount_cents=line.amount_cents,
        period_start=line.period_start,
        period_end=line.period_end,
    )


def _payment(payment: domain.Payment) -> Payment:
    return Payment(
        id=payment.id,
        invoice_id=payment.invoice_id,
        amount_cents=payment.amount_cents,
        method=payment.method,
        status=payment.status,
        paid_at=payment.paid_at,
        reference=payment.reference,
    )


def _subscription(subscription: domain.Subscription) -> Subscription:
    return Subscription(
        id=subscription.id,
        account_id=subscription.account_id,
        plan_id=subscription.plan_id,
        status=subscription.status,
        seats=subscription.seats,
        started_at=subscription.started_at,
        renews_at=subscription.renews_at,
        cancelled_at=subscription.cancelled_at,
        version=subscription.version,
    )


def _account(account: domain.Account) -> Account:
    return Account(
        id=account.id,
        name=account.name,
        slug=account.slug,
        plan_id=account.plan_id,
        status=account.status,
        seat_limit=account.seat_limit,
        country=account.country,
        segment=account.segment,
        created_at=account.created_at,
        version=account.version,
    )
