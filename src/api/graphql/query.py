"""The GraphQL query surface."""

from __future__ import annotations

from typing import Any

import strawberry
from strawberry.scalars import JSON

from api.graphql.errors import map_errors
from api.graphql.types import (
    Account,
    AccountPage,
    AccountStatusGQL,
    Agent,
    Contact,
    Invoice,
    InvoicePage,
    InvoiceStatusGQL,
    KbArticle,
    PartialFailureDemo,
    Plan,
    RevenueByPlanRow,
    SqlResult,
    Subscription,
    Ticket,
    TicketAtRiskRow,
    TicketPage,
    TicketPriorityGQL,
    TicketStatusGQL,
    TopAgentRow,
    UsageTrendRow,
    _account,
    _agent,
    _article,
    _contact,
    _invoice,
    _plan,
    _subscription,
    _ticket,
)


def _date(value: Any) -> str:
    if value is None:
        return ""
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


@strawberry.type
class Query:
    """Everything an agent or a browser can ask for."""

    @strawberry.field(description="Accounts, with keyset pagination")
    def accounts(
        self,
        info: strawberry.Info,
        status: AccountStatusGQL | None = None,
        plan: str | None = None,
        segment: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> AccountPage:
        services = info.context.services
        page = map_errors(
            lambda: services.accounts.list_accounts(
                status=status.value if status else None,
                plan=plan,
                segment=segment,
                limit=limit,
                cursor=cursor,
            )
        )
        return AccountPage(items=[_account(a) for a in page.items], next_cursor=page.next_cursor)

    @strawberry.field(description="One account by id")
    def account(self, info: strawberry.Info, id: int) -> Account:
        services = info.context.services
        account = map_errors(lambda: services.accounts.get_account(id))
        return _account(account)

    @strawberry.field(description="The contacts of an account")
    def contacts(self, info: strawberry.Info, account_id: int) -> list[Contact]:
        services = info.context.services
        contacts = map_errors(lambda: services.accounts.get_contacts(account_id))
        return [_contact(contact) for contact in contacts]

    @strawberry.field(description="Tickets, with keyset pagination")
    def tickets(
        self,
        info: strawberry.Info,
        account_id: int | None = None,
        status: TicketStatusGQL | None = None,
        priority: TicketPriorityGQL | None = None,
        category: str | None = None,
        tag: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> TicketPage:
        services = info.context.services
        page = map_errors(
            lambda: services.tickets.list_tickets(
                account_id=account_id,
                status=status.value if status else None,
                priority=priority.value if priority else None,
                category=category,
                tag=tag,
                limit=limit,
                cursor=cursor,
            )
        )
        return TicketPage(items=[_ticket(t) for t in page.items], next_cursor=page.next_cursor)

    @strawberry.field(description="One ticket by id")
    def ticket(self, info: strawberry.Info, id: int) -> Ticket:
        services = info.context.services
        ticket = map_errors(lambda: services.tickets.get_ticket(id))
        return _ticket(ticket)

    @strawberry.field(
        description="A ticket with its messages, the shape that shows the N+1 trap"
    )
    def ticket_with_messages(self, info: strawberry.Info, id: int) -> Ticket:
        services = info.context.services
        ticket = map_errors(lambda: services.tickets.get_ticket(id))
        return _ticket(ticket)

    @strawberry.field(description="The subscription of an account")
    def subscription(self, info: strawberry.Info, account_id: int) -> Subscription | None:
        services = info.context.services
        subscription = map_errors(
            lambda: services.subscriptions.get_subscription_for_account(account_id)
        )
        return None if subscription is None else _subscription(subscription)

    @strawberry.field(description="One subscription by id")
    def subscription_by_id(self, info: strawberry.Info, id: int) -> Subscription:
        services = info.context.services
        subscription = map_errors(lambda: services.subscriptions.get_subscription(id))
        return _subscription(subscription)

    @strawberry.field(description="Invoices, with keyset pagination")
    def invoices(
        self,
        info: strawberry.Info,
        account_id: int | None = None,
        status: InvoiceStatusGQL | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> InvoicePage:
        services = info.context.services
        page = map_errors(
            lambda: services.invoices.list_invoices(
                account_id=account_id,
                status=status.value if status else None,
                limit=limit,
                cursor=cursor,
            )
        )
        return InvoicePage(items=[_invoice(i) for i in page.items], next_cursor=page.next_cursor)

    @strawberry.field(description="One invoice by id")
    def invoice(self, info: strawberry.Info, id: int) -> Invoice:
        services = info.context.services
        invoice = map_errors(lambda: services.invoices.get_invoice(id))
        return _invoice(invoice)

    @strawberry.field(description="The support agents")
    def agents(self, info: strawberry.Info, team: str | None = None) -> list[Agent]:
        services = info.context.services
        agents = services.repo.list_agents(team)
        return [_agent(agent) for agent in agents]

    @strawberry.field(description="The knowledge base articles")
    def kb_articles(self, info: strawberry.Info, category: str | None = None, q: str | None = None) -> list[KbArticle]:
        services = info.context.services
        articles = services.repo.search_kb_articles(category=category, q=q)
        return [_article(article) for article in articles]

    @strawberry.field(description="The plans")
    def plans(self, info: strawberry.Info) -> list[Plan]:
        services = info.context.services
        return [_plan(plan) for plan in services.repo.list_plans()]

    @strawberry.field(description="Revenue per plan and period, answered by DuckDB")
    def revenue_by_plan(
        self,
        info: strawberry.Info,
        date_from: str = "2000-01-01",
        date_to: str = "2999-12-31",
        granularity: str = "month",
    ) -> list[RevenueByPlanRow]:
        services = info.context.services
        result = map_errors(
            lambda: services.analytics.revenue_by_plan(date_from, date_to, granularity)
        )
        return [
            RevenueByPlanRow(
                period=_date(row.get("period")),
                plan_code=row.get("plan_code"),
                revenue_cents=int(row.get("revenue_cents") or 0),
                invoices=int(row.get("invoices") or 0),
            )
            for row in result["rows"]
        ]

    @strawberry.field(description="Usage trends per account, answered by DuckDB")
    def usage_trends(
        self,
        info: strawberry.Info,
        metric: str = "tickets_opened",
        account_id: int | None = None,
        date_from: str = "2000-01-01",
        date_to: str = "2999-12-31",
    ) -> list[UsageTrendRow]:
        services = info.context.services
        result = map_errors(
            lambda: services.analytics.usage_trends(
                metric=metric, account_id=account_id, date_from=date_from, date_to=date_to
            )
        )
        return [
            UsageTrendRow(
                date=_date(row.get("date")),
                account_id=int(row.get("account_id") or 0),
                total=float(row.get("total") or 0),
            )
            for row in result["rows"]
        ]

    @strawberry.field(
        description="Accounts with an overdue invoice and open critical tickets"
    )
    def tickets_at_risk(
        self, info: strawberry.Info, threshold: int = 0, reference_date: str | None = None
    ) -> list[TicketAtRiskRow]:
        services = info.context.services
        result = map_errors(
            lambda: services.analytics.tickets_at_risk(reference_date, threshold)
        )
        return [
            TicketAtRiskRow(
                account_id=int(row.get("account_id") or 0),
                account_name=row.get("account_name"),
                plan_code=row.get("plan_code"),
                segment=row.get("segment"),
                overdue_cents=int(row.get("overdue_cents") or 0),
                overdue_invoices=int(row.get("overdue_invoices") or 0),
                critical_open=int(row.get("critical_open") or 0),
                revenue_at_risk_cents=int(row.get("revenue_at_risk_cents") or 0),
            )
            for row in result["rows"]
        ]

    @strawberry.field(description="The busiest agents, answered by DuckDB")
    def top_agents(
        self, info: strawberry.Info, date_from: str = "2000-01-01", date_to: str = "2999-12-31", limit: int = 10
    ) -> list[TopAgentRow]:
        services = info.context.services
        result = map_errors(lambda: services.analytics.top_agents(date_from, date_to, limit))
        return [
            TopAgentRow(
                agent_id=int(row.get("agent_id") or 0),
                agent_name=row.get("agent_name"),
                team=row.get("team"),
                tickets=int(row.get("tickets") or 0),
                avg_response_seconds=(
                    float(row["avg_response_seconds"]) if row.get("avg_response_seconds") is not None else None
                ),
            )
            for row in result["rows"]
        ]

    @strawberry.field(description="Run an allowlisted analytical query")
    def run_sql(
        self, info: strawberry.Info, sql: str, params: JSON | None = None, row_cap: int = 1_000
    ) -> SqlResult:
        services = info.context.services
        result = map_errors(lambda: services.analytics.run_sql(sql, params or [], row_cap))
        return SqlResult(
            columns=result["columns"], rows=result["rows"], row_count=result["row_count"]
        )

    @strawberry.field(
        description="Shows how a failing field bubbles up, required fields versus optional ones"
    )
    def partial_failure_demo(
        self, fail_required: bool = False, fail_optional: bool = False
    ) -> PartialFailureDemo:
        return PartialFailureDemo(fail_required=fail_required, fail_optional=fail_optional)

    @strawberry.field(description="The reference business question, answered by DuckDB")
    def revenue_at_risk_summary(self, info: strawberry.Info, reference_date: str | None = None) -> JSON:
        services = info.context.services
        return map_errors(lambda: services.analytics.revenue_at_risk_summary(reference_date))
