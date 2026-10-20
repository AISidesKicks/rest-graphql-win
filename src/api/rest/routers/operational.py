"""REST routers for the operational (SQLite) side."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Request, Response

from api.rest.errors import parse_if_match
from api.rest.schemas import (
    AccountOut,
    AccountPage,
    AccountUpdate,
    AgentOut,
    ChangePlanOut,
    ChangePlanRequest,
    ContactOut,
    InvoiceLineOut,
    InvoiceOut,
    InvoicePage,
    KbArticleOut,
    PaymentCreate,
    PaymentOut,
    PaymentResultOut,
    PlanOut,
    SubscriptionOut,
    TicketCloseOut,
    TicketCreate,
    TicketMessageCreate,
    TicketMessageOut,
    TicketOut,
    TicketPage,
    TicketUpdate,
)
from observability.tracing import span
from services import Services

router = APIRouter(prefix="/api", tags=["operational"])


def get_services(request: Request) -> Services:
    return request.app.state.services


ServicesDep = Annotated[Services, Depends(get_services)]


@router.get("/accounts", response_model=AccountPage, operation_id="rest_list_accounts")
def list_accounts(
    services: ServicesDep,
    status: str | None = Query(default=None),
    plan: str | None = Query(default=None),
    segment: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    cursor: str | None = Query(default=None),
) -> AccountPage:
    page = services.accounts.list_accounts(
        status=status, plan=plan, segment=segment, limit=limit, cursor=cursor
    )
    return AccountPage(items=page.items, next_cursor=page.next_cursor)


@router.get("/accounts/{account_id}", response_model=AccountOut, operation_id="rest_get_account")
def get_account(account_id: int, services: ServicesDep, response: Response) -> AccountOut:
    account = services.accounts.get_account(account_id)
    response.headers["ETag"] = f'"{account.version}"'
    return AccountOut.model_validate(account)


@router.get(
    "/accounts/{account_id}/contacts",
    response_model=list[ContactOut],
    operation_id="rest_list_account_contacts",
)
def list_account_contacts(account_id: int, services: ServicesDep) -> list[ContactOut]:
    return [ContactOut.model_validate(contact) for contact in services.accounts.get_contacts(account_id)]


@router.patch("/accounts/{account_id}", response_model=AccountOut, operation_id="rest_update_account")
def update_account(
    account_id: int,
    payload: AccountUpdate,
    services: ServicesDep,
    response: Response,
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> AccountOut:
    body = payload.model_dump(exclude_none=True)
    expected = parse_if_match(if_match)
    if expected is None:
        expected = body.pop("version", None)
    else:
        body.pop("version", None)
    account = services.accounts.update_account(account_id, body, expected_version=expected)
    response.headers["ETag"] = f'"{account.version}"'
    return AccountOut.model_validate(account)


@router.get(
    "/accounts/{account_id}/tickets", response_model=TicketPage, operation_id="rest_list_account_tickets"
)
def list_account_tickets(
    account_id: int,
    services: ServicesDep,
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    cursor: str | None = Query(default=None),
) -> TicketPage:
    services.accounts.get_account(account_id)
    page = services.tickets.list_tickets(account_id=account_id, status=status, limit=limit, cursor=cursor)
    return TicketPage(items=page.items, next_cursor=page.next_cursor)


@router.get("/tickets", response_model=TicketPage, operation_id="rest_list_tickets")
def list_tickets(
    services: ServicesDep,
    account_id: int | None = Query(default=None),
    status: str | None = Query(default=None),
    priority: str | None = Query(default=None),
    category: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    cursor: str | None = Query(default=None),
) -> TicketPage:
    page = services.tickets.list_tickets(
        account_id=account_id,
        status=status,
        priority=priority,
        category=category,
        tag=tag,
        limit=limit,
        cursor=cursor,
    )
    return TicketPage(items=page.items, next_cursor=page.next_cursor)


@router.get("/tickets/{ticket_id}", response_model=TicketOut, operation_id="rest_get_ticket")
def get_ticket(ticket_id: int, services: ServicesDep, response: Response) -> TicketOut:
    ticket = services.tickets.get_ticket(ticket_id)
    response.headers["ETag"] = f'"{ticket.version}"'
    return TicketOut.model_validate(ticket)


@router.get(
    "/tickets/{ticket_id}/messages",
    response_model=list[TicketMessageOut],
    operation_id="rest_list_ticket_messages",
)
def list_ticket_messages(ticket_id: int, services: ServicesDep) -> list[TicketMessageOut]:
    messages = services.tickets.get_messages(ticket_id)
    return [TicketMessageOut.model_validate(message) for message in messages]


@router.post("/tickets", response_model=TicketOut, status_code=201, operation_id="rest_create_ticket")
def create_ticket(payload: TicketCreate, services: ServicesDep, response: Response) -> TicketOut:
    ticket = services.tickets.create_ticket(
        account_id=payload.account_id,
        subject=payload.subject,
        priority=payload.priority,
        category=payload.category,
        contact_id=payload.contact_id,
        agent_id=payload.agent_id,
        actor="rest",
    )
    response.headers["ETag"] = f'"{ticket.version}"'
    return TicketOut.model_validate(ticket)


@router.patch("/tickets/{ticket_id}", response_model=TicketOut, operation_id="rest_update_ticket")
def update_ticket(
    ticket_id: int,
    payload: TicketUpdate,
    services: ServicesDep,
    response: Response,
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> TicketOut:
    body = payload.model_dump(exclude_none=True)
    expected = parse_if_match(if_match)
    if expected is None:
        expected = body.pop("version", None)
    else:
        body.pop("version", None)
    ticket = services.tickets.update_ticket(ticket_id, body, expected_version=expected)
    response.headers["ETag"] = f'"{ticket.version}"'
    return TicketOut.model_validate(ticket)


@router.post(
    "/tickets/{ticket_id}/messages",
    response_model=TicketMessageOut,
    status_code=201,
    operation_id="rest_add_ticket_message",
)
def add_ticket_message(
    ticket_id: int, payload: TicketMessageCreate, services: ServicesDep
) -> TicketMessageOut:
    message = services.tickets.add_message(
        ticket_id,
        body=payload.body,
        author_type=payload.author_type,
        author_id=payload.author_id,
        actor="rest",
    )
    return TicketMessageOut.model_validate(message)


@router.post(
    "/tickets/{ticket_id}/close",
    response_model=TicketCloseOut,
    operation_id="rest_close_ticket",
)
def close_ticket(
    ticket_id: int,
    services: ServicesDep,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> TicketCloseOut:
    result = services.tickets.close_ticket(
        ticket_id, idempotency_key=idempotency_key, actor="rest"
    )
    return TicketCloseOut.model_validate(result)


@router.get("/plans", response_model=list[PlanOut], operation_id="rest_list_plans")
def list_plans(services: ServicesDep) -> list[PlanOut]:
    return [PlanOut.model_validate(plan) for plan in services.repo.list_plans()]


@router.get(
    "/subscriptions", response_model=list[SubscriptionOut], operation_id="rest_list_subscriptions"
)
def list_subscriptions(
    services: ServicesDep, account_id: int | None = Query(default=None)
) -> list[SubscriptionOut]:
    subscriptions = services.subscriptions.list_subscriptions(account_id)
    return [SubscriptionOut.model_validate(subscription) for subscription in subscriptions]


@router.get(
    "/subscriptions/{subscription_id}",
    response_model=SubscriptionOut,
    operation_id="rest_get_subscription",
)
def get_subscription(subscription_id: int, services: ServicesDep, response: Response) -> SubscriptionOut:
    subscription = services.subscriptions.get_subscription(subscription_id)
    response.headers["ETag"] = f'"{subscription.version}"'
    return SubscriptionOut.model_validate(subscription)


@router.post(
    "/subscriptions/{subscription_id}/change_plan",
    response_model=ChangePlanOut,
    operation_id="rest_change_plan",
)
def change_plan(
    subscription_id: int,
    payload: ChangePlanRequest,
    services: ServicesDep,
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ChangePlanOut:
    expected = parse_if_match(if_match)
    if expected is None:
        expected = payload.version
    result = services.subscriptions.change_plan(
        subscription_id,
        new_plan_code=payload.new_plan_code,
        seats=payload.seats,
        expected_version=expected,
        idempotency_key=idempotency_key,
        actor="rest",
    )
    return ChangePlanOut.model_validate(result)


@router.post(
    "/subscriptions/{subscription_id}/cancel",
    response_model=SubscriptionOut,
    operation_id="rest_cancel_subscription",
)
def cancel_subscription(
    subscription_id: int,
    services: ServicesDep,
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> SubscriptionOut:
    expected = parse_if_match(if_match)
    subscription = services.subscriptions.cancel_subscription(
        subscription_id, expected_version=expected, actor="rest"
    )
    return SubscriptionOut.model_validate(subscription)


@router.get("/invoices", response_model=InvoicePage, operation_id="rest_list_invoices")
def list_invoices(
    services: ServicesDep,
    account_id: int | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    cursor: str | None = Query(default=None),
) -> InvoicePage:
    page = services.invoices.list_invoices(
        account_id=account_id, status=status, limit=limit, cursor=cursor
    )
    return InvoicePage(items=page.items, next_cursor=page.next_cursor)


@router.get("/invoices/{invoice_id}", response_model=InvoiceOut, operation_id="rest_get_invoice")
def get_invoice(invoice_id: int, services: ServicesDep, response: Response) -> InvoiceOut:
    invoice = services.invoices.get_invoice(invoice_id)
    response.headers["ETag"] = f'"{invoice.version}"'
    return InvoiceOut.model_validate(invoice)


@router.get(
    "/invoices/{invoice_id}/lines",
    response_model=list[InvoiceLineOut],
    operation_id="rest_list_invoice_lines",
)
def list_invoice_lines(invoice_id: int, services: ServicesDep) -> list[InvoiceLineOut]:
    lines = services.invoices.get_lines(invoice_id)
    return [InvoiceLineOut.model_validate(line) for line in lines]


@router.post(
    "/invoices/{invoice_id}/payments",
    response_model=PaymentResultOut,
    status_code=201,
    operation_id="rest_record_payment",
)
def record_payment(
    invoice_id: int,
    payload: PaymentCreate,
    services: ServicesDep,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> PaymentResultOut:
    result = services.invoices.record_payment(
        invoice_id,
        amount_cents=payload.amount_cents,
        method=payload.method,
        idempotency_key=idempotency_key,
        actor="rest",
    )
    return PaymentResultOut.model_validate(result)


@router.get("/invoices/{invoice_id}/payments", response_model=list[PaymentOut], operation_id="rest_list_payments")
def list_payments(invoice_id: int, services: ServicesDep) -> list[PaymentOut]:
    payments = services.invoices.get_payments(invoice_id)
    return [PaymentOut.model_validate(payment) for payment in payments]


@router.get("/agents", response_model=list[AgentOut], operation_id="rest_list_agents")
def list_agents(services: ServicesDep, team: str | None = Query(default=None)) -> list[AgentOut]:
    agents = services.repo.list_agents(team)
    return [AgentOut.model_validate(agent) for agent in agents]


@router.get("/kb/articles", response_model=list[KbArticleOut], operation_id="rest_search_kb_articles")
def search_kb_articles(
    services: ServicesDep,
    category: str | None = Query(default=None),
    q: str | None = Query(default=None),
) -> list[KbArticleOut]:
    articles = services.repo.search_kb_articles(category=category, q=q)
    return [KbArticleOut.model_validate(article) for article in articles]


@router.get("/audit/{entity_type}/{entity_id}", response_model=list[dict[str, Any]], operation_id="rest_audit_trail")
def audit_trail(entity_type: str, entity_id: int, services: ServicesDep) -> list[dict[str, Any]]:
    with span("rest.audit_trail", entity_type=entity_type, entity_id=entity_id):
        events = services.repo.list_audit_events(entity_type, entity_id, 100)
        return [
            {
                "id": event.id,
                "entity_type": event.entity_type,
                "entity_id": event.entity_id,
                "kind": event.kind,
                "actor": event.actor,
                "payload": event.payload_json,
                "created_at": event.created_at,
            }
            for event in events
        ]
