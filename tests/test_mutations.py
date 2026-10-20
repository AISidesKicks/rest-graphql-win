"""Write semantics: concurrency, idempotency, atomicity and error mapping.

These rules are the core of the lab, so they get tested on both API styles.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from domain.errors import IdempotencyMismatchError, RuleViolationError, VersionConflictError


def _open_ticket(client: TestClient) -> dict:
    tickets = client.get("/api/tickets?status=open&limit=1").json()["items"]
    assert tickets
    return tickets[0]


def _subscription(client: TestClient) -> dict:
    subscriptions = client.get("/api/subscriptions").json()
    assert subscriptions
    return subscriptions[0]


def test_a_stale_version_is_a_conflict(services):
    account = services.accounts.list_accounts(limit=1).items[0]
    with pytest.raises(VersionConflictError):
        services.accounts.update_account(account.id, {"seat_limit": 5}, expected_version=999)


def test_the_right_version_updates_the_entity(services):
    account = services.accounts.list_accounts(limit=1).items[0]
    updated = services.accounts.update_account(
        account.id, {"seat_limit": account.seat_limit + 1}, expected_version=account.version
    )
    assert updated.version == account.version + 1


def test_closing_a_ticket_twice_without_a_key_is_a_rule_violation(services):
    ticket = services.tickets.list_tickets(status="open", limit=1).items[0]
    services.tickets.close_ticket(ticket.id)
    with pytest.raises(RuleViolationError):
        services.tickets.close_ticket(ticket.id)


def test_the_same_idempotency_key_replays_the_first_answer(services):
    ticket = services.tickets.list_tickets(status="open", limit=1).items[0]
    first = services.tickets.close_ticket(ticket.id, idempotency_key="close-1")
    second = services.tickets.close_ticket(ticket.id, idempotency_key="close-1")
    assert first["replayed"] is False
    assert second["replayed"] is True
    assert first["version"] == second["version"]


def test_the_same_idempotency_key_with_another_payload_is_a_mismatch(services):
    first_ticket = services.tickets.list_tickets(status="open", limit=1).items[0]
    second_ticket = services.tickets.list_tickets(status="open", limit=2).items[1]
    services.tickets.close_ticket(first_ticket.id, idempotency_key="close-shared")
    with pytest.raises(IdempotencyMismatchError):
        services.tickets.close_ticket(second_ticket.id, idempotency_key="close-shared")


def test_a_plan_change_writes_every_table(services):
    subscription = services.subscriptions.list_subscriptions()[0]
    before_invoices = services.repo.list_invoices(account_id=subscription.account_id, limit=500)
    result = services.subscriptions.change_plan(
        subscription.id, new_plan_code="growth", seats=5, expected_version=subscription.version
    )
    assert result["to_plan"] == "growth"
    assert result["seats"] == 5
    after_invoices = services.repo.list_invoices(account_id=subscription.account_id, limit=500)
    assert len(after_invoices.items) == len(before_invoices.items) + 1

    updated = services.subscriptions.get_subscription(subscription.id)
    assert updated.version == subscription.version + 1


def test_a_failing_plan_change_rolls_everything_back(services):
    subscription = services.subscriptions.list_subscriptions()[1]
    before = services.subscriptions.get_subscription(subscription.id)
    before_invoices = services.repo.list_invoices(account_id=subscription.account_id, limit=500)

    def fail_after_invoice(step: str) -> None:
        if step == "invoice":
            raise RuntimeError("the invoice could not be written")

    with pytest.raises(RuntimeError):
        services.subscriptions.change_plan(
            subscription.id,
            new_plan_code="starter",
            seats=3,
            expected_version=before.version,
            fail_hook=fail_after_invoice,
        )

    after = services.subscriptions.get_subscription(subscription.id)
    assert after.version == before.version
    assert after.plan_id == before.plan_id
    assert after.seats == before.seats
    after_invoices = services.repo.list_invoices(account_id=subscription.account_id, limit=500)
    assert len(after_invoices.items) == len(before_invoices.items)


def test_a_plan_change_to_an_unknown_plan_is_a_rule_violation(services):
    subscription = services.subscriptions.list_subscriptions()[2]
    with pytest.raises(RuleViolationError):
        services.subscriptions.change_plan(subscription.id, new_plan_code="does-not-exist")


def test_a_payment_moves_the_invoice_to_paid(services):
    invoice = next(
        item
        for item in services.invoices.list_invoices(status="open", limit=50).items
        if item.total_cents > 0
    )
    result = services.invoices.record_payment(
        invoice.id, amount_cents=invoice.total_cents, method="card", idempotency_key="pay-1"
    )
    assert result["invoice_status"] == "paid"
    assert result["total_paid_cents"] == invoice.total_cents
    replay = services.invoices.record_payment(
        invoice.id, amount_cents=invoice.total_cents, method="card", idempotency_key="pay-1"
    )
    assert replay["replayed"] is True


def test_a_payment_beyond_the_total_is_refused(services):
    invoice = next(
        item
        for item in services.invoices.list_invoices(status="open", limit=50).items
        if item.total_cents > 0
    )
    with pytest.raises(RuleViolationError):
        services.invoices.record_payment(invoice.id, amount_cents=invoice.total_cents + 1)


def test_rest_and_graphql_report_the_same_rule_differently(client):
    missing_rest = client.get("/api/accounts/99999999")
    assert missing_rest.status_code == 404
    assert missing_rest.json()["error"]["code"] == "NOT_FOUND"

    missing_graphql = client.post("/graphql", json={"query": "{ account(id: 99999999) { id } }"})
    assert missing_graphql.status_code == 200
    errors = missing_graphql.json()["errors"]
    assert errors[0]["extensions"]["code"] == "NOT_FOUND"


def test_rest_and_graphql_agree_on_a_version_conflict(client):
    ticket = _open_ticket(client)

    rest = client.patch(
        f"/api/tickets/{ticket['id']}",
        json={"priority": "high"},
        headers={"If-Match": '"999"'},
    )
    assert rest.status_code == 409
    assert rest.json()["error"]["code"] == "VERSION_CONFLICT"

    graphql = client.post(
        "/graphql",
        json={
            "query": """
            mutation Update($id: Int!, $version: Int) {
              updateTicket(id: $id, input: {priority: HIGH}, expectedVersion: $version) { id }
            }
            """,
            "variables": {"id": ticket["id"], "version": 999},
        },
    )
    assert graphql.status_code == 200
    assert graphql.json()["errors"][0]["extensions"]["code"] == "VERSION_CONFLICT"


def test_graphql_returns_the_first_answer_on_a_replay(client):
    ticket = _open_ticket(client)
    mutation = """
    mutation Close($id: Int!, $version: Int, $key: String) {
      closeTicket(ticketId: $id, expectedVersion: $version, idempotencyKey: $key) {
        ticketId version replayed
      }
    }
    """
    variables = {
        "id": ticket["id"],
        "version": ticket["version"],
        "key": f"gql-close-{uuid.uuid4().hex}",
    }
    first = client.post("/graphql", json={"query": mutation, "variables": variables}).json()
    second = client.post("/graphql", json={"query": mutation, "variables": variables}).json()
    assert first["data"]["closeTicket"]["replayed"] is False
    assert second["data"]["closeTicket"]["replayed"] is True


def test_the_partial_failure_demo_shows_both_behaviours(client):
    optional = client.post(
        "/graphql", json={"query": "{ partialFailureDemo(failOptional: true) { required optional } }"}
    ).json()
    assert optional["data"]["partialFailureDemo"]["optional"] is None
    assert optional["data"]["partialFailureDemo"]["required"] is not None

    required = client.post(
        "/graphql", json={"query": "{ partialFailureDemo(failRequired: true) { required optional } }"}
    ).json()
    assert required["data"]["partialFailureDemo"] is None
    assert required["errors"]
