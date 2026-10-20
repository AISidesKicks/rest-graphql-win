"""Tests for the CodeMode sandbox."""

from __future__ import annotations

import pytest


@pytest.fixture()
def runner(client):
    return client.app.state.code_mode


def test_a_good_program_runs_and_calls_the_lab(runner):
    result = runner.run(
        """
plans = list_plans()
print("plans", len(plans))
len(plans)
"""
    )
    assert result.error is None
    assert result.host_calls == 1
    assert "plans 4" in result.stdout
    assert result.value == 4


def test_the_program_cannot_import_a_module(runner):
    result = runner.run("import socket\n")
    assert result.error is not None
    assert "socket" in result.error


def test_the_program_cannot_open_a_file(runner):
    result = runner.run('open("/etc/passwd").read()\n')
    assert result.error is not None or result.value in (None, "/")


def test_a_runaway_program_is_stopped(runner):
    result = runner.run("while True:\n    pass\n")
    assert result.error is not None
    assert "ime" in result.error or "imeout" in result.error


def test_the_host_call_limit_is_enforced(runner):
    result = runner.run(
        """
for index in range(500):
    list_plans()
"""
    )
    assert result.error is not None
    assert "host call" in result.error or "suspension limit" in result.error


def test_the_output_size_is_capped(seeded_db, olap_db):
    from fastapi.testclient import TestClient

    from app import create_app
    from config import load_settings

    settings = load_settings()
    settings.oltp_path = seeded_db
    settings.olap_path = olap_db
    settings.code_mode_max_output_bytes = 50
    app = create_app(settings)
    with TestClient(app):
        result = app.state.code_mode.run('print("x" * 5000)\n')
    assert result.truncated is True
    assert len(result.stdout) == 50


def test_the_render_hides_nothing_important(runner):
    result = runner.run('print("hello")\n')
    assert "hello" in result.render()


def test_the_host_functions_cover_the_whole_catalog(runner):
    functions = runner.host_functions()
    assert "list_accounts" in functions
    assert "graphql_query" in functions
    assert "tickets_at_risk" in functions


def test_the_stubs_describe_the_functions(runner):
    stubs = runner.stubs()
    assert "def list_accounts(" in stubs
    assert "def graphql_query(" in stubs


def test_a_graphql_call_from_the_sandbox_works(runner):
    result = runner.run(
        """
document = "{ accounts(limit: 2) { items { id name } } }"
payload = graphql_query(query=document)
print("accounts", len(payload["data"]["accounts"]["items"]))
"""
    )
    assert result.error is None
    assert "accounts 2" in result.stdout
