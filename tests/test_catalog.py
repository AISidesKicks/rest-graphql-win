"""Tests for the MCP catalog: names, schemas and the exposure switch."""

from __future__ import annotations

import pytest

from config import EXPOSURE_CURATED, EXPOSURE_GRAPHQL, EXPOSURE_REST, parse_exposure
from mcplab.catalog import ToolCatalog, build_rest_tools, count_tokens


@pytest.fixture()
def app_with_catalog(client):
    return client.app


def test_the_catalog_is_built_from_the_live_openapi_document(app_with_catalog):
    catalog = app_with_catalog.state.mcp_catalog
    openapi = app_with_catalog.openapi()
    operation_ids = {
        operation["operationId"]
        for path, item in openapi["paths"].items()
        if not path.startswith("/graphql")
        for method, operation in item.items()
        if method in {"get", "post", "put", "patch", "delete"}
    }
    tool_names = {tool.name for tool in catalog.tools if tool.group == EXPOSURE_REST}
    assert operation_ids == tool_names


def test_the_graphql_routes_are_not_published_as_rest_tools(app_with_catalog):
    catalog = app_with_catalog.state.mcp_catalog
    assert not [tool for tool in catalog.tools if tool.path and tool.path.startswith("/graphql")]


def test_the_catalog_holds_the_three_groups(app_with_catalog):
    groups = app_with_catalog.state.mcp_catalog.groups()
    assert groups[EXPOSURE_REST] > 20
    assert groups[EXPOSURE_GRAPHQL] == 1
    assert groups[EXPOSURE_CURATED] == 5


def test_the_exposure_switch_shrinks_the_catalog(app_with_catalog):
    catalog = app_with_catalog.state.mcp_catalog
    full = len(catalog.tools)

    curated_only = ToolCatalog(
        app_with_catalog.openapi(),
        app_with_catalog.state.services,
        frozenset({EXPOSURE_CURATED}),
    )
    assert len(curated_only.tools) == 5
    assert all(tool.group == EXPOSURE_CURATED for tool in curated_only.tools)
    assert len(curated_only.tools) < full

    rest_only = ToolCatalog(
        app_with_catalog.openapi(),
        app_with_catalog.state.services,
        frozenset({EXPOSURE_REST}),
    )
    assert all(tool.group == EXPOSURE_REST for tool in rest_only.tools)


def test_the_exposure_spec_accepts_mixes():
    assert parse_exposure("all") == frozenset({EXPOSURE_REST, EXPOSURE_GRAPHQL, EXPOSURE_CURATED})
    assert parse_exposure("rest,curated") == frozenset({EXPOSURE_REST, EXPOSURE_CURATED})
    assert parse_exposure(" REST , GraphQL ") == frozenset({EXPOSURE_REST, EXPOSURE_GRAPHQL})
    with pytest.raises(ValueError):
        parse_exposure("rest,nonsense")


def test_the_tool_schemas_carry_their_arguments(app_with_catalog):
    catalog = app_with_catalog.state.mcp_catalog
    by_name = catalog.by_name()
    list_accounts = by_name["rest_list_accounts"]
    assert "status" in list_accounts.input_schema["properties"]
    assert "limit" in list_accounts.input_schema["properties"]
    assert list_accounts.param_locations["status"] == "query"

    get_account = by_name["rest_get_account"]
    assert get_account.param_locations["account_id"] == "path"

    change_plan = by_name["rest_change_plan"]
    assert change_plan.param_locations["if_match"] == "header"
    assert change_plan.header_names["if_match"] == "If-Match"
    assert change_plan.param_locations["idempotency_key"] == "header"


def test_the_graphql_tool_takes_a_document_and_variables(app_with_catalog):
    catalog = app_with_catalog.state.mcp_catalog
    graphql_tool = catalog.by_name()["graphql_query"]
    assert graphql_tool.input_schema["required"] == ["query"]
    assert "variables" in graphql_tool.input_schema["properties"]


def test_the_code_mode_names_stay_unique(app_with_catalog):
    catalog = app_with_catalog.state.mcp_catalog
    names = catalog.code_mode_names()
    assert len(set(names.values())) == len(names)
    assert names["rest_list_accounts"] == "list_accounts"
    assert names["revenue_by_plan"] == "revenue_by_plan"
    assert names["rest_revenue_by_plan"] == "rest_revenue_by_plan"


def test_the_schema_token_report_counts_every_tool(app_with_catalog):
    from mcplab.catalog import schema_token_report

    catalog = app_with_catalog.state.mcp_catalog
    report = schema_token_report(catalog)
    assert report["tool_count"] == len(catalog.tools)
    assert report["total_tokens"] > 0
    assert sum(item["tokens"] for item in report["tools"]) == report["total_tokens"]


def test_the_token_counter_works_offline():
    assert count_tokens("hello world") > 0
    assert count_tokens({"a": 1}) > 0


def test_the_catalog_survives_a_document_without_operation_ids():
    tools = build_rest_tools({"paths": {"/api/thing": {"get": {"responses": {}}}}})
    assert tools == []
