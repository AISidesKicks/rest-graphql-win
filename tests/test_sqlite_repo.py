"""Repository level tests: queries, keyset pagination and the write paths."""

from __future__ import annotations

import pytest

from domain.errors import NotFoundError, RuleViolationError


def test_account_list_is_paginated_with_a_cursor(repo):
    first = repo.list_accounts(limit=10)
    assert len(first.items) == 10
    assert first.next_cursor is not None

    second = repo.list_accounts(limit=10, cursor=first.next_cursor)
    assert len(second.items) == 10
    assert [item.id for item in first.items] != [item.id for item in second.items]
    assert second.items[0].id > first.items[-1].id


def test_account_filters_narrow_the_result(repo):
    past_due = repo.list_accounts(status="past_due", limit=100)
    assert past_due.items
    assert all(account.status == "past_due" for account in past_due.items)

    by_plan = repo.list_accounts(plan="enterprise", limit=100)
    assert all(account.plan_id == 4 for account in by_plan.items)


def test_tickets_are_ordered_by_creation_time(repo):
    page = repo.list_tickets(limit=20)
    timestamps = [ticket.created_at for ticket in page.items]
    assert timestamps == sorted(timestamps, reverse=True)


def test_ticket_cursor_continues_after_the_last_row(repo):
    first = repo.list_tickets(limit=5)
    second = repo.list_tickets(limit=5, cursor=first.next_cursor)
    assert first.items[-1].id != second.items[0].id
    assert second.items[0].created_at <= first.items[-1].created_at


def test_tickets_can_be_filtered_by_tag(repo):
    tagged = repo.list_tickets(tag="vip", limit=20)
    assert tagged.items
    tags = repo.list_ticket_tags(tagged.items[0].id)
    assert "vip" in tags


def test_invoices_are_paginated(repo):
    page = repo.list_invoices(limit=7)
    assert len(page.items) == 7
    assert page.next_cursor is not None


def test_agents_and_kb_articles(repo):
    agents = repo.list_agents()
    assert len(agents) == 40
    billing = repo.list_agents(team="billing")
    assert billing and all(agent.team == "billing" for agent in billing)

    articles = repo.search_kb_articles(q="invoice")
    assert articles


def test_update_account_only_moves_with_the_right_version(repo):
    account = repo.list_accounts(limit=1).items[0]
    assert repo.update_account(account.id, account.version, {"seat_limit": 42}) is True
    assert repo.get_account(account.id).seat_limit == 42
    assert repo.update_account(account.id, account.version, {"seat_limit": 7}) is False


def test_audit_events_are_written_for_mutations(repo):
    account = repo.list_accounts(limit=1).items[0]
    with repo.transaction():
        repo.update_account(account.id, account.version, {"name": "Renamed Ltd"})
        repo.insert_audit_event(
            "account", account.id, "account.updated", "test", {"name": "Renamed Ltd"}, "2026-01-01"
        )
    events = repo.list_audit_events("account", account.id)
    assert any(event.kind == "account.updated" for event in events)


def test_missing_entities_raise_not_found(services):
    with pytest.raises(NotFoundError):
        services.accounts.get_account(999_999_99)
    with pytest.raises(NotFoundError):
        services.tickets.get_ticket(999_999_99)
    with pytest.raises(NotFoundError):
        services.invoices.get_invoice(999_999_99)


def test_the_operational_at_risk_query_matches_the_analytical_one(services):
    reference_date = "2026-06-30"
    operational = services.analytics.revenue_at_risk_operational(reference_date, 50)
    analytical = services.analytics.tickets_at_risk(reference_date, 0, 50)
    assert operational["row_count"] > 0
    assert operational["row_count"] == analytical["row_count"]
    assert operational["rows"][0]["account_id"] == analytical["rows"][0]["account_id"]


def test_analytical_sql_is_allowlisted(services):
    with pytest.raises(RuleViolationError):
        services.analytics.run_sql("SELECT * FROM sqlite_master")
    with pytest.raises(RuleViolationError):
        services.analytics.run_sql("DROP TABLE accounts")
    with pytest.raises(RuleViolationError):
        services.analytics.run_sql("SELECT 1; SELECT 2")
