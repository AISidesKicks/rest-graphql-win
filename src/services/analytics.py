"""Analytical rules, the DuckDB side of the lab."""

from __future__ import annotations

from typing import Any

from data.duckdb_repo import DuckDbRepo, SqlResult
from data.sqlite_repo import SqliteRepo
from domain.clock import now
from domain.errors import RuleViolationError
from observability.tracing import span


class AnalyticsService:
    """Queries the columnar star schema, and the operational tables for comparison."""

    def __init__(self, repo: DuckDbRepo, oltp: SqliteRepo | None = None) -> None:
        self.repo = repo
        self.oltp = oltp

    def _guard(self) -> None:
        if not self.repo.available():
            raise RuleViolationError(
                "the analytical database is missing, run 'pixi run etl' first"
            )

    def revenue_by_plan(self, date_from: str, date_to: str, granularity: str = "month") -> dict[str, Any]:
        self._guard()
        with span("service.analytics.revenue_by_plan", granularity=granularity):
            result = self.repo.revenue_by_plan(date_from, date_to, granularity)
            return result.to_dict()

    def usage_trends(
        self,
        metric: str = "tickets_opened",
        account_id: int | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict[str, Any]:
        self._guard()
        anchor = now().date().isoformat()
        date_from = date_from or "2000-01-01"
        date_to = date_to or anchor
        with span("service.analytics.usage_trends", metric=metric, account_id=account_id):
            result = self.repo.usage_trends(account_id, metric, date_from, date_to)
            return result.to_dict()

    def tickets_at_risk(
        self, reference_date: str | None = None, threshold_cents: int = 0, limit: int = 50
    ) -> dict[str, Any]:
        self._guard()
        reference_date = reference_date or now().date().isoformat()
        with span("service.analytics.tickets_at_risk", reference_date=reference_date):
            result = self.repo.tickets_at_risk(reference_date, threshold_cents, limit)
            return result.to_dict()

    def top_agents(self, date_from: str | None = None, date_to: str | None = None, limit: int = 10) -> dict[str, Any]:
        self._guard()
        anchor = now().date().isoformat()
        date_from = date_from or "2000-01-01"
        date_to = date_to or anchor
        with span("service.analytics.top_agents", limit=limit):
            result = self.repo.top_agents(date_from, date_to, limit)
            return result.to_dict()

    def plan_usage_summary(self, account_id: int) -> dict[str, Any]:
        self._guard()
        with span("service.analytics.plan_usage_summary", account_id=account_id):
            result = self.repo.plan_usage_summary(account_id)
            return result.to_dict()

    def run_sql(self, sql: str, params: list[Any] | None = None, row_cap: int = 5_000) -> dict[str, Any]:
        self._guard()
        with span("service.analytics.run_sql"):
            result: SqlResult = self.repo.run_sql(sql, params or [], row_cap)
            return result.to_dict()

    def revenue_at_risk_summary(self, reference_date: str | None = None) -> dict[str, Any]:
        self._guard()
        reference_date = reference_date or now().date().isoformat()
        result = self.repo.revenue_at_risk_summary(reference_date)
        return result.to_dict()

    def revenue_at_risk_operational(
        self, reference_date: str | None = None, limit: int = 50
    ) -> dict[str, Any]:
        """The same question, answered by SQLite with joins over the operational tables."""
        if self.oltp is None:
            raise RuleViolationError("the operational repository is not available")
        reference_date = reference_date or now().date().isoformat()
        with span("service.analytics.revenue_at_risk_operational", reference_date=reference_date):
            rows = self.oltp.revenue_at_risk_operational(reference_date, limit)
            return {
                "columns": list(rows[0].keys()) if rows else [],
                "rows": rows,
                "row_count": len(rows),
            }
