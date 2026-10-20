"""REST routers for the analytical (DuckDB) side."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from api.rest.schemas import AnalyticsQueryOut, SqlQueryIn
from observability.tracing import span
from services import Services

router = APIRouter(prefix="/api/analytics", tags=["analytical"])


def get_services(request: Request) -> Services:
    return request.app.state.services


ServicesDep = Annotated[Services, Depends(get_services)]


@router.get("/revenue-by-plan", response_model=AnalyticsQueryOut, operation_id="rest_revenue_by_plan")
def revenue_by_plan(
    services: ServicesDep,
    date_from: Annotated[str, Query(alias="from")] = "2000-01-01",
    date_to: Annotated[str, Query(alias="to")] = "2999-12-31",
    granularity: str = Query(default="month"),
) -> AnalyticsQueryOut:
    result = services.analytics.revenue_by_plan(date_from, date_to, granularity)
    return AnalyticsQueryOut.model_validate(result)


@router.get("/usage-trends", response_model=AnalyticsQueryOut, operation_id="rest_usage_trends")
def usage_trends(
    services: ServicesDep,
    account_id: int | None = Query(default=None),
    metric: str = Query(default="tickets_opened"),
    date_from: Annotated[str | None, Query(alias="from")] = None,
    date_to: Annotated[str | None, Query(alias="to")] = None,
) -> AnalyticsQueryOut:
    result = services.analytics.usage_trends(
        metric=metric, account_id=account_id, date_from=date_from, date_to=date_to
    )
    return AnalyticsQueryOut.model_validate(result)


@router.get("/tickets-at-risk", response_model=AnalyticsQueryOut, operation_id="rest_tickets_at_risk")
def tickets_at_risk(
    services: ServicesDep,
    threshold: int = Query(default=0, description="minimum revenue at risk in cents"),
    reference_date: str | None = Query(default=None),
) -> AnalyticsQueryOut:
    result = services.analytics.tickets_at_risk(reference_date, threshold)
    return AnalyticsQueryOut.model_validate(result)


@router.get("/top-agents", response_model=AnalyticsQueryOut, operation_id="rest_top_agents")
def top_agents(
    services: ServicesDep,
    date_from: Annotated[str | None, Query(alias="from")] = None,
    date_to: Annotated[str | None, Query(alias="to")] = None,
    limit: int = Query(default=10, ge=1, le=100),
) -> AnalyticsQueryOut:
    result = services.analytics.top_agents(date_from, date_to, limit)
    return AnalyticsQueryOut.model_validate(result)


@router.post("/query", response_model=AnalyticsQueryOut, operation_id="rest_run_sql")
def run_sql(payload: SqlQueryIn, services: ServicesDep) -> AnalyticsQueryOut:
    with span("rest.analytics.query"):
        result = services.analytics.run_sql(payload.sql, payload.params, payload.row_cap)
        return AnalyticsQueryOut.model_validate(result)
