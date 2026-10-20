"""The GraphQL mutation surface.

Every mutation takes the concurrency token and the idempotency key as
arguments, while REST takes them from headers. The rules behind them are the
same, the shape is not.
"""

from __future__ import annotations

import strawberry

from api.graphql.errors import map_errors
from api.graphql.types import (
    Account,
    ChangePlanPayload,
    CloseTicketPayload,
    CreateTicketInput,
    RecordPaymentPayload,
    Subscription,
    Ticket,
    TicketMessage,
    UpdateAccountInput,
    UpdateTicketInput,
    _account,
    _message,
    _subscription,
    _ticket,
)


@strawberry.type
class Mutation:
    """Everything that changes state."""

    @strawberry.mutation(description="Open a new ticket")
    def create_ticket(self, info: strawberry.Info, input: CreateTicketInput) -> Ticket:
        services = info.context.services
        ticket = map_errors(
            lambda: services.tickets.create_ticket(
                account_id=input.account_id,
                subject=input.subject,
                priority=input.priority.value,
                category=input.category,
                contact_id=input.contact_id,
                agent_id=input.agent_id,
                actor="graphql",
            )
        )
        return _ticket(ticket)

    @strawberry.mutation(description="Update a ticket, guarded by the expected version")
    def update_ticket(
        self,
        info: strawberry.Info,
        id: int,
        input: UpdateTicketInput,
        expected_version: int | None = None,
    ) -> Ticket:
        services = info.context.services
        changes = {
            key: value
            for key, value in {
                "subject": input.subject,
                "priority": input.priority.value if input.priority else None,
                "category": input.category,
                "status": input.status.value if input.status else None,
                "agent_id": input.agent_id,
            }.items()
            if value is not None
        }
        ticket = map_errors(
            lambda: services.tickets.update_ticket(
                id, changes, expected_version=expected_version, actor="graphql"
            )
        )
        return _ticket(ticket)

    @strawberry.mutation(description="Add a message to a ticket")
    def add_ticket_message(
        self,
        info: strawberry.Info,
        ticket_id: int,
        body: str,
        author_type: str = "customer",
        author_id: int | None = None,
    ) -> TicketMessage:
        services = info.context.services
        message = map_errors(
            lambda: services.tickets.add_message(
                ticket_id,
                body=body,
                author_type=author_type,
                author_id=author_id,
                actor="graphql",
            )
        )
        return _message(message)

    @strawberry.mutation(description="Close a ticket, guarded by version and idempotency key")
    def close_ticket(
        self,
        info: strawberry.Info,
        ticket_id: int,
        expected_version: int | None = None,
        idempotency_key: str | None = None,
    ) -> CloseTicketPayload:
        services = info.context.services
        result = map_errors(
            lambda: services.tickets.close_ticket(
                ticket_id,
                expected_version=expected_version,
                idempotency_key=idempotency_key,
                actor="graphql",
            )
        )
        return CloseTicketPayload(**result)

    @strawberry.mutation(
        description="Move a subscription to another plan, one transaction for every table"
    )
    def change_plan(
        self,
        info: strawberry.Info,
        subscription_id: int,
        new_plan_code: str,
        seats: int | None = None,
        expected_version: int | None = None,
        idempotency_key: str | None = None,
    ) -> ChangePlanPayload:
        services = info.context.services
        result = map_errors(
            lambda: services.subscriptions.change_plan(
                subscription_id,
                new_plan_code=new_plan_code,
                seats=seats,
                expected_version=expected_version,
                idempotency_key=idempotency_key,
                actor="graphql",
            )
        )
        return ChangePlanPayload(**result)

    @strawberry.mutation(description="Cancel a subscription")
    def cancel_subscription(
        self, info: strawberry.Info, id: int, expected_version: int | None = None
    ) -> Subscription:
        services = info.context.services
        subscription = map_errors(
            lambda: services.subscriptions.cancel_subscription(
                id, expected_version=expected_version, actor="graphql"
            )
        )
        return _subscription(subscription)

    @strawberry.mutation(description="Record a payment against an invoice")
    def record_payment(
        self,
        info: strawberry.Info,
        invoice_id: int,
        amount_cents: int,
        method: str = "card",
        idempotency_key: str | None = None,
    ) -> RecordPaymentPayload:
        services = info.context.services
        result = map_errors(
            lambda: services.invoices.record_payment(
                invoice_id,
                amount_cents=amount_cents,
                method=method,
                idempotency_key=idempotency_key,
                actor="graphql",
            )
        )
        return RecordPaymentPayload(**result)

    @strawberry.mutation(description="Update an account, guarded by the expected version")
    def update_account(
        self,
        info: strawberry.Info,
        id: int,
        input: UpdateAccountInput,
        expected_version: int | None = None,
    ) -> Account:
        services = info.context.services
        changes = {
            key: value
            for key, value in {
                "name": input.name,
                "status": input.status.value if input.status else None,
                "seat_limit": input.seat_limit,
                "segment": input.segment,
                "country": input.country,
            }.items()
            if value is not None
        }
        account = map_errors(
            lambda: services.accounts.update_account(
                id, changes, expected_version=expected_version, actor="graphql"
            )
        )
        return _account(account)
