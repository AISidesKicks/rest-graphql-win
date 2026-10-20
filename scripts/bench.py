"""Compare REST and GraphQL on the reference business question.

The script answers one question both ways and prints the numbers: how many
calls, how many round trips, how many milliseconds, how many rows, how many
bytes over the wire.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi.testclient import TestClient  # noqa: E402

from app import create_app  # noqa: E402
from config import load_settings  # noqa: E402

QUESTION = "How much revenue is at risk from accounts with an overdue invoice and open critical tickets?"


def _timed(callable_):
    started = time.perf_counter()
    payload = callable_()
    elapsed = (time.perf_counter() - started) * 1000
    return payload, elapsed


def bench_rest(client: TestClient) -> dict[str, Any]:
    """The REST way: a small chain of calls."""
    calls: list[dict[str, Any]] = []
    started = time.perf_counter()

    def record(name: str, path: str, payload: Any, elapsed: float) -> None:
        text = json.dumps(payload, default=str)
        calls.append(
            {
                "call": name,
                "path": path,
                "ms": round(elapsed, 2),
                "bytes": len(text),
                "rows": _rows(payload),
            }
        )

    accounts, elapsed = _timed(lambda: client.get("/api/accounts?status=past_due&limit=50").json())
    record("accounts at risk", "/api/accounts?status=past_due&limit=50", accounts, elapsed)

    invoices, elapsed = _timed(lambda: client.get("/api/invoices?status=overdue&limit=50").json())
    record("overdue invoices", "/api/invoices?status=overdue&limit=50", invoices, elapsed)

    tickets, elapsed = _timed(
        lambda: client.get("/api/tickets?status=open&priority=critical&limit=50").json()
    )
    record("critical open tickets", "/api/tickets?status=open&priority=critical&limit=50", tickets, elapsed)

    plans, elapsed = _timed(lambda: client.get("/api/plans").json())
    record("plans", "/api/plans", plans, elapsed)

    total = time.perf_counter() - started
    return {
        "style": "REST",
        "calls": len(calls),
        "round_trips": len(calls),
        "wall_time_ms": round(total * 1000, 2),
        "bytes": sum(call["bytes"] for call in calls),
        "rows": sum(call["rows"] for call in calls),
        "details": calls,
    }


def bench_graphql(client: TestClient) -> dict[str, Any]:
    """The GraphQL way: one request, the same data the REST chain fetches."""
    query = """
    query RevenueAtRisk {
      accounts(status: PAST_DUE, limit: 50) { items { id name plan { code monthlyPriceCents } } }
      invoices(status: OVERDUE, limit: 50) { items { accountId totalCents dueAt } }
      tickets(status: OPEN, priority: CRITICAL, limit: 50) { items { accountId id subject priority } }
    }
    """
    started = time.perf_counter()
    payload = client.post("/graphql", json={"query": query}).json()
    elapsed = (time.perf_counter() - started) * 1000
    text = json.dumps(payload, default=str)
    return {
        "style": "GraphQL",
        "calls": 1,
        "round_trips": 1,
        "wall_time_ms": round(elapsed, 2),
        "bytes": len(text),
        "rows": _rows(payload),
        "details": [
            {
                "call": "one query, three root fields",
                "path": "/graphql",
                "ms": round(elapsed, 2),
                "bytes": len(text),
                "rows": _rows(payload),
            }
        ],
    }


def bench_graphql_nested(client: TestClient) -> dict[str, Any]:
    """The GraphQL way, nested: one account with its invoices and its tickets."""
    query = """
    query RevenueAtRiskNested {
      accounts(status: PAST_DUE, limit: 10) {
        items {
          id
          name
          plan { code monthlyPriceCents }
          invoices(status: OVERDUE, limit: 20) { totalCents dueAt }
          tickets(status: OPEN, priority: CRITICAL, limit: 20) { id subject priority }
        }
      }
    }
    """
    started = time.perf_counter()
    payload = client.post("/graphql", json={"query": query}).json()
    elapsed = (time.perf_counter() - started) * 1000
    text = json.dumps(payload, default=str)
    return {
        "style": "GraphQL nested",
        "calls": 1,
        "round_trips": 1,
        "wall_time_ms": round(elapsed, 2),
        "bytes": len(text),
        "rows": _rows(payload),
        "details": [
            {
                "call": "one query, nested fields",
                "path": "/graphql",
                "ms": round(elapsed, 2),
                "bytes": len(text),
                "rows": _rows(payload),
            }
        ],
    }


def bench_duckdb(client: TestClient) -> dict[str, Any]:
    """The analytical way: one columnar scan."""
    started = time.perf_counter()
    payload = client.get("/api/analytics/tickets-at-risk").json()
    elapsed = (time.perf_counter() - started) * 1000
    text = json.dumps(payload, default=str)
    return {
        "style": "DuckDB",
        "calls": 1,
        "round_trips": 1,
        "wall_time_ms": round(elapsed, 2),
        "bytes": len(text),
        "rows": _rows(payload),
        "details": [
            {
                "call": "one scan",
                "path": "/api/analytics/tickets-at-risk",
                "ms": round(elapsed, 2),
                "bytes": len(text),
                "rows": _rows(payload),
            }
        ],
    }


def bench_sqlite(app: Any, client: TestClient) -> dict[str, Any]:
    """The same question on the operational engine, joins over the operational tables."""
    services = app.state.services
    started = time.perf_counter()
    payload = services.analytics.revenue_at_risk_operational("2026-06-30", 50)
    elapsed = (time.perf_counter() - started) * 1000
    text = json.dumps(payload, default=str)
    return {
        "style": "SQLite",
        "calls": 1,
        "round_trips": 1,
        "wall_time_ms": round(elapsed, 2),
        "bytes": len(text),
        "rows": _rows(payload),
        "details": [
            {
                "call": "one join over the operational tables",
                "path": "service.analytics.revenue_at_risk_operational",
                "ms": round(elapsed, 2),
                "bytes": len(text),
                "rows": _rows(payload),
            }
        ],
    }


def _rows(payload: Any) -> int:
    if isinstance(payload, dict):
        if "errors" in payload:
            return 0
        if "items" in payload and isinstance(payload["items"], list):
            return len(payload["items"])
        if "rows" in payload and isinstance(payload["rows"], list):
            return len(payload["rows"])
        data = payload.get("data")
        if isinstance(data, dict):
            total = 0
            for value in data.values():
                total += _rows(value)
            return total
    if isinstance(payload, list):
        return len(payload)
    return 0


def print_table(results: list[dict[str, Any]]) -> None:
    header = f"{'style':<10} {'calls':>6} {'round trips':>12} {'ms':>9} {'bytes':>9} {'rows':>7}"
    print(header)
    print("-" * len(header))
    for result in results:
        print(
            f"{result['style']:<10} {result['calls']:>6} {result['round_trips']:>12} "
            f"{result['wall_time_ms']:>9.2f} {result['bytes']:>9,} {result['rows']:>7,}"
        )


def main() -> int:
    settings = load_settings()
    parser = argparse.ArgumentParser(description="Compare REST and GraphQL")
    parser.add_argument("--json", action="store_true", help="print the raw numbers")
    args = parser.parse_args()

    app = create_app(settings)
    with TestClient(app) as client:
        results = [
            bench_rest(client),
            bench_graphql(client),
            bench_graphql_nested(client),
            bench_sqlite(app, client),
            bench_duckdb(client),
        ]

    print(f"question: {QUESTION}")
    print()
    print_table(results)
    print()
    for result in results:
        for detail in result["details"]:
            print(
                f"  {result['style']:<10} {detail['call']:<26} "
                f"{detail['ms']:>8.2f} ms  {detail['bytes']:>8,} bytes  {detail['rows']:>6,} rows"
            )
    if args.json:
        print()
        print(json.dumps(results, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
