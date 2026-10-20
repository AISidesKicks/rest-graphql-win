"""End to end check of the whole lab.

The script boots the app on a free port, runs a REST read, a REST write, a
GraphQL query, a GraphQL mutation, a partial failure demo, an MCP handshake
with a tools list and one code mode program, then prints the comparison tables.
No network access needed, everything happens on localhost.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import socket
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import httpx  # noqa: E402
import uvicorn  # noqa: E402

from app import create_app  # noqa: E402
from config import load_settings  # noqa: E402

PASS = "PASS"
FAIL = "FAIL"


class Checks:
    """A tiny check list, so the output stays readable."""

    def __init__(self) -> None:
        self.results: list[tuple[str, bool, str]] = []

    def check(self, name: str, condition: bool, detail: str = "") -> bool:
        self.results.append((name, condition, detail))
        status = PASS if condition else FAIL
        print(f"  [{status}] {name}{(' - ' + detail) if detail else ''}")
        return condition

    @property
    def failed(self) -> int:
        return sum(1 for _name, ok, _detail in self.results if not ok)

    def summary(self) -> None:
        passed = len(self.results) - self.failed
        print()
        print(f"{passed}/{len(self.results)} checks passed")
        if self.failed:
            for name, ok, detail in self.results:
                if not ok:
                    print(f"  failed: {name} {detail}")


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def run_rest(checks: Checks, client: httpx.Client) -> None:
    print("REST")
    response = client.get("/api/accounts?limit=5")
    checks.check("GET /api/accounts", response.status_code == 200, f"status {response.status_code}")
    accounts = response.json().get("items", [])
    checks.check("the account list has rows", len(accounts) == 5, f"{len(accounts)} rows")

    if accounts:
        account_id = accounts[0]["id"]
        one = client.get(f"/api/accounts/{account_id}")
        checks.check("GET /api/accounts/{id}", one.status_code == 200, f"status {one.status_code}")
        checks.check(
            "the read carries an ETag",
            "etag" in {key.lower() for key in one.headers},
            one.headers.get("etag", "missing"),
        )

    missing = client.get("/api/accounts/99999999")
    checks.check(
        "a missing account is a 404",
        missing.status_code == 404,
        f"status {missing.status_code} body {missing.text[:80]}",
    )


def run_rest_write(checks: Checks, client: httpx.Client) -> None:
    print("REST writes")
    tickets = client.get("/api/tickets?status=open&limit=1").json().get("items", [])
    if not tickets:
        checks.check("an open ticket to work with", False, "the dataset has no open ticket")
        return
    ticket = tickets[0]

    stale = client.patch(
        f"/api/tickets/{ticket['id']}",
        json={"priority": "high"},
        headers={"If-Match": '"999"'},
    )
    checks.check(
        "a stale If-Match is a 409",
        stale.status_code == 409,
        f"status {stale.status_code} body {stale.text[:120]}",
    )

    fresh = client.patch(
        f"/api/tickets/{ticket['id']}",
        json={"priority": "high"},
        headers={"If-Match": f'"{ticket["version"]}"'},
    )
    checks.check(
        "a fresh If-Match updates the ticket",
        fresh.status_code == 200,
        f"status {fresh.status_code}",
    )

    key = f"verify-close-{uuid.uuid4().hex}"
    closed = client.post(
        f"/api/tickets/{ticket['id']}/close",
        headers={"Idempotency-Key": key},
    )
    checks.check("closing a ticket works", closed.status_code == 200, f"status {closed.status_code}")
    replay = client.post(
        f"/api/tickets/{ticket['id']}/close",
        headers={"Idempotency-Key": key},
    )
    checks.check(
        "the replay of the close returns the first answer",
        replay.status_code == 200 and replay.json().get("replayed") is True,
        replay.text[:120],
    )


def run_graphql(checks: Checks, client: httpx.Client) -> None:
    print("GraphQL")
    query = "{ accounts(limit: 3) { items { id name status plan { code } } } }"
    response = client.post("/graphql", json={"query": query})
    payload = response.json()
    checks.check("the GraphQL query works", "errors" not in payload, json.dumps(payload)[:160])
    checks.check(
        "GraphQL answers with HTTP 200",
        response.status_code == 200,
        f"status {response.status_code}",
    )

    missing = client.post("/graphql", json={"query": "{ account(id: 99999999) { id } }"})
    body = missing.json()
    checks.check(
        "a missing account is an error in the payload",
        body.get("errors") is not None,
        json.dumps(body)[:160],
    )
    extensions = (body.get("errors") or [{}])[0].get("extensions") or {}
    checks.check(
        "the error carries extensions.code",
        extensions.get("code") == "NOT_FOUND",
        json.dumps(extensions),
    )
    checks.check(
        "GraphQL still answers with HTTP 200 on an error",
        missing.status_code == 200,
        f"status {missing.status_code}",
    )


def run_graphql_mutation(checks: Checks, client: httpx.Client) -> None:
    print("GraphQL mutations")
    mutation = """
    mutation CloseOne($id: Int!, $version: Int, $key: String) {
      closeTicket(ticketId: $id, expectedVersion: $version, idempotencyKey: $key) {
        ticketId status version replayed
      }
    }
    """
    tickets = client.get("/api/tickets?status=open&limit=1").json().get("items", [])
    if not tickets:
        checks.check("an open ticket to close", False, "the dataset has no open ticket")
        return
    ticket = tickets[0]
    key = f"verify-gql-close-{uuid.uuid4().hex}"

    stale = client.post(
        "/graphql",
        json={
            "query": mutation,
            "variables": {"id": ticket["id"], "version": 999, "key": key},
        },
    ).json()
    extensions = (stale.get("errors") or [{}])[0].get("extensions") or {}
    checks.check(
        "a stale expectedVersion is a VERSION_CONFLICT",
        extensions.get("code") == "VERSION_CONFLICT",
        json.dumps(stale)[:160],
    )

    ok = client.post(
        "/graphql",
        json={
            "query": mutation,
            "variables": {
                "id": ticket["id"],
                "version": ticket["version"],
                "key": key,
            },
        },
    ).json()
    checks.check("the mutation closes the ticket", "errors" not in ok, json.dumps(ok)[:160])

    replay = client.post(
        "/graphql",
        json={
            "query": mutation,
            "variables": {
                "id": ticket["id"],
                "version": ticket["version"],
                "key": key,
            },
        },
    ).json()
    payload = (replay.get("data") or {}).get("closeTicket") or {}
    checks.check(
        "the replay returns the first answer",
        payload.get("replayed") is True,
        json.dumps(replay)[:160],
    )


def run_partial_failure(checks: Checks, client: httpx.Client) -> None:
    print("GraphQL partial failure")
    query = "{ partialFailureDemo(failOptional: true) { required optional } }"
    payload = client.post("/graphql", json={"query": query}).json()
    data = (payload.get("data") or {}).get("partialFailureDemo") or {}
    checks.check(
        "a failing nullable field only nulls itself",
        data.get("optional") is None and data.get("required") is not None,
        json.dumps(payload)[:200],
    )

    query = "{ partialFailureDemo(failRequired: true) { required optional } }"
    payload = client.post("/graphql", json={"query": query}).json()
    data = (payload.get("data") or {}).get("partialFailureDemo")
    checks.check(
        "a failing non null field bubbles up",
        data is None and payload.get("errors"),
        json.dumps(payload)[:200],
    )


def run_mcp(checks: Checks, port: int) -> None:
    print("MCP")
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    async def handshake() -> dict[str, Any]:
        url = f"http://127.0.0.1:{port}/mcp"
        async with streamable_http_client(url) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                return {"tools": [tool.name for tool in tools.tools]}

    try:
        result = asyncio.run(handshake())
    except Exception as exc:
        checks.check("the MCP handshake works", False, f"{type(exc).__name__}: {exc}")
        return
    checks.check("the MCP handshake works", True, f"{len(result['tools'])} tools")
    checks.check(
        "the catalog holds the REST tools",
        any(name.startswith("rest_") for name in result["tools"]),
        ", ".join(result["tools"][:5]),
    )
    checks.check(
        "the catalog holds the curated tools",
        "tickets_at_risk" in result["tools"],
        ", ".join(result["tools"][-5:]),
    )


def run_code_mode(checks: Checks, app: Any) -> None:
    print("Code mode")
    runner = app.state.code_mode
    program = """
plans = list_plans()
print("plans", len(plans))
accounts = list_accounts(status="past_due", limit=3)
print("accounts at risk", len(accounts["items"]))
"""
    result = runner.run(program)
    checks.check("the program runs", result.error is None, str(result.error)[:160])
    checks.check(
        "the program calls the lab functions",
        result.host_calls == 2,
        f"{result.host_calls} host calls",
    )
    checks.check(
        "the output comes back",
        "plans" in result.stdout,
        result.stdout.strip()[:80],
    )

    blocked = runner.run("import socket\n")
    checks.check(
        "the sandbox refuses an import",
        blocked.error is not None,
        str(blocked.error)[:120],
    )

    loop = runner.run("while True:\n    pass\n")
    checks.check(
        "the sandbox stops a runaway program",
        loop.error is not None,
        str(loop.error)[:120],
    )


def main() -> int:
    settings = load_settings()
    parser = argparse.ArgumentParser(description="Verify the whole lab")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    checks = Checks()
    app = create_app(settings)
    port = free_port()

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)

    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=60) as client:
            run_rest(checks, client)
            run_rest_write(checks, client)
            run_graphql(checks, client)
            run_graphql_mutation(checks, client)
            run_partial_failure(checks, client)
        run_mcp(checks, port)
        run_code_mode(checks, app)
    finally:
        server.should_exit = True
        thread.join(timeout=5)

    checks.summary()
    return 1 if checks.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
