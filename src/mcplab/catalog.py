"""The MCP tool catalog.

The catalog is built from the live ``/openapi.json`` of the running app, so it
can never drift away from the REST surface. The same catalog drives two things:

- the native MCP tools the model calls one by one
- the typed Python functions the CodeMode sandbox exposes

Because both come from one list, the token comparison in the savings chapter is
honest.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from config import EXPOSURE_CURATED, EXPOSURE_GRAPHQL, EXPOSURE_REST
from observability.tracing import span

HTTP_METHODS = {"get", "post", "put", "patch", "delete"}


@dataclass
class ToolSpec:
    """One publishable tool."""

    name: str
    group: str
    description: str
    input_schema: dict[str, Any]
    kind: str = "rest"
    method: str | None = None
    path: str | None = None
    has_body: bool = False
    param_locations: dict[str, str] = field(default_factory=dict)
    header_names: dict[str, str] = field(default_factory=dict)
    original_names: dict[str, str] = field(default_factory=dict)
    required: list[str] = field(default_factory=list)

    @property
    def arguments(self) -> list[str]:
        return list(self.input_schema.get("properties", {}).keys())

    def signature(self) -> str:
        """A Python style signature, used for the CodeMode stubs."""
        parts = []
        for name in self.arguments:
            if name in self.required:
                parts.append(name)
            else:
                parts.append(f"{name}=None")
        return f"def {self.name}({', '.join(parts)}): ..."

    def stub(self) -> str:
        """A ``.pyi`` stub for the CodeMode sandbox."""
        types = {
            "integer": "int",
            "number": "float",
            "string": "str",
            "boolean": "bool",
            "array": "list",
            "object": "dict",
        }
        parts = []
        for name in self.arguments:
            schema = self.input_schema.get("properties", {}).get(name, {})
            hint = types.get(schema.get("type", "string"), "Any")
            if name in self.required:
                parts.append(f"{name}: {hint}")
            else:
                parts.append(f"{name}: {hint} | None = None")
        return f"def {self.name}({', '.join(parts)}) -> Any: ..."

    def as_mcp_tool(self) -> dict[str, Any]:
        """The shape the MCP ``tools/list`` endpoint returns."""
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }


def _argument_name(name: str) -> str:
    """Turn an OpenAPI parameter name into a friendly tool argument."""
    cleaned = name.replace("-", "_").replace(".", "_").lower()
    return cleaned


def resolve_ref(openapi: dict[str, Any], ref: str) -> dict[str, Any]:
    """Resolve a local ``$ref`` against the OpenAPI document."""
    if not ref.startswith("#/"):
        return {}
    node: Any = openapi
    for part in ref[2:].split("/"):
        node = node.get(part, {}) if isinstance(node, dict) else {}
    return node


def deref(openapi: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    """Follow a ``$ref`` until a real schema shows up."""
    seen = 0
    while isinstance(schema, dict) and "$ref" in schema and seen < 10:
        schema = resolve_ref(openapi, schema["$ref"])
        seen += 1
    return schema or {}


def build_rest_tools(openapi: dict[str, Any]) -> list[ToolSpec]:
    """Turn every REST operation into a tool."""
    tools: list[ToolSpec] = []
    for path, item in (openapi.get("paths") or {}).items():
        if path.startswith("/graphql"):
            continue
        for method, operation in item.items():
            if method.lower() not in HTTP_METHODS or not isinstance(operation, dict):
                continue
            operation_id = operation.get("operationId")
            if not operation_id:
                continue
            properties: dict[str, Any] = {}
            required: list[str] = []
            locations: dict[str, str] = {}
            headers: dict[str, str] = {}
            originals: dict[str, str] = {}

            for parameter in operation.get("parameters") or []:
                name = parameter.get("name")
                if not name:
                    continue
                schema = deref(openapi, parameter.get("schema") or {})
                location = parameter.get("in", "query")
                argument_name = _argument_name(name)
                properties[argument_name] = schema or {"type": "string"}
                locations[argument_name] = location
                originals[argument_name] = name
                if location == "header":
                    headers[argument_name] = name
                if parameter.get("required"):
                    required.append(argument_name)

            body_schema = (
                (operation.get("requestBody") or {})
                .get("content", {})
                .get("application/json", {})
                .get("schema")
            )
            has_body = body_schema is not None
            if body_schema:
                body_schema = deref(openapi, body_schema)
                for name, schema in (body_schema.get("properties") or {}).items():
                    properties[name] = deref(openapi, schema)
                    locations[name] = "body"
                for name in body_schema.get("required") or []:
                    if name not in required:
                        required.append(name)

            description = (
                operation.get("summary")
                or operation.get("description")
                or f"{method.upper()} {path}"
            )
            tools.append(
                ToolSpec(
                    name=operation_id,
                    group=EXPOSURE_REST,
                    description=description,
                    input_schema={
                        "type": "object",
                        "properties": properties,
                        "required": required,
                    },
                    kind="rest",
                    method=method.upper(),
                    path=path,
                    has_body=has_body,
                    param_locations=locations,
                    header_names=headers,
                    original_names=originals,
                    required=required,
                )
            )
    return tools


def build_graphql_tools() -> list[ToolSpec]:
    """The GraphQL side of the catalog."""
    return [
        ToolSpec(
            name="graphql_query",
            group=EXPOSURE_GRAPHQL,
            description=(
                "Run a GraphQL document against /graphql. "
                "Returns the data and the errors array as one JSON object."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "the GraphQL document"},
                    "variables": {
                        "type": "object",
                        "description": "the variables of the document",
                    },
                },
                "required": ["query"],
            },
            kind="graphql",
            required=["query"],
        )
    ]


def build_curated_tools() -> list[ToolSpec]:
    """Business level tools, ready to use without composing raw requests."""
    return [
        ToolSpec(
            name="revenue_by_plan",
            group=EXPOSURE_CURATED,
            description="Revenue per plan and period, answered by DuckDB.",
            input_schema={
                "type": "object",
                "properties": {
                    "date_from": {"type": "string"},
                    "date_to": {"type": "string"},
                    "granularity": {"type": "string", "enum": ["day", "week", "month", "quarter"]},
                },
                "required": [],
            },
            kind="curated",
        ),
        ToolSpec(
            name="tickets_at_risk",
            group=EXPOSURE_CURATED,
            description=(
                "Accounts with an overdue invoice and open critical tickets, "
                "with the revenue at risk in cents."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "threshold": {"type": "integer", "description": "minimum revenue at risk in cents"},
                    "reference_date": {"type": "string"},
                },
                "required": [],
            },
            kind="curated",
        ),
        ToolSpec(
            name="top_agents",
            group=EXPOSURE_CURATED,
            description="The busiest agents over a period.",
            input_schema={
                "type": "object",
                "properties": {
                    "date_from": {"type": "string"},
                    "date_to": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": [],
            },
            kind="curated",
        ),
        ToolSpec(
            name="open_tickets_for_account",
            group=EXPOSURE_CURATED,
            description="The open tickets of one account.",
            input_schema={
                "type": "object",
                "properties": {
                    "account_id": {"type": "integer"},
                    "limit": {"type": "integer"},
                },
                "required": ["account_id"],
            },
            kind="curated",
            required=["account_id"],
        ),
        ToolSpec(
            name="plan_usage_summary",
            group=EXPOSURE_CURATED,
            description="Usage of one account against its plan.",
            input_schema={
                "type": "object",
                "properties": {"account_id": {"type": "integer"}},
                "required": ["account_id"],
            },
            kind="curated",
            required=["account_id"],
        ),
    ]


class ToolCatalog:
    """All tools, filtered by the exposure switch."""

    def __init__(
        self,
        openapi: dict[str, Any],
        services: Any,
        exposure: frozenset[str],
    ) -> None:
        self.services = services
        self.exposure = exposure
        self.all_tools: list[ToolSpec] = []
        if EXPOSURE_REST in exposure:
            self.all_tools.extend(build_rest_tools(openapi))
        if EXPOSURE_GRAPHQL in exposure:
            self.all_tools.extend(build_graphql_tools())
        if EXPOSURE_CURATED in exposure:
            self.all_tools.extend(build_curated_tools())
        self.tools: list[ToolSpec] = list(self.all_tools)

    def by_name(self) -> dict[str, ToolSpec]:
        return {tool.name: tool for tool in self.tools}

    def groups(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for tool in self.tools:
            counts[tool.group] = counts.get(tool.group, 0) + 1
        return counts

    def code_mode_names(self) -> dict[str, str]:
        """The Python function name of every tool inside the sandbox.

        The curated and the GraphQL tools keep their clean names, the REST
        tools drop the ``rest_`` prefix unless that name is already taken.
        """
        mapping: dict[str, str] = {}
        taken: set[str] = set()
        for group in (EXPOSURE_CURATED, EXPOSURE_GRAPHQL):
            for tool in self.tools:
                if tool.group == group:
                    mapping[tool.name] = tool.name
                    taken.add(tool.name)
        for tool in self.tools:
            if tool.group != EXPOSURE_REST:
                continue
            candidate = tool.name[len("rest_") :] if tool.name.startswith("rest_") else tool.name
            if candidate in taken:
                candidate = tool.name
            mapping[tool.name] = candidate
            taken.add(candidate)
        return mapping

    def as_mcp_tools(self) -> list[dict[str, Any]]:
        return [tool.as_mcp_tool() for tool in self.tools]


def count_tokens(payload: Any) -> int:
    """Count the tokens of a payload, with a fallback when tiktoken is offline."""
    text = payload if isinstance(payload, str) else json.dumps(payload, default=str)
    try:
        import tiktoken

        encoding = tiktoken.get_encoding("cl100k_base")
        return len(encoding.encode(text))
    except Exception:
        return max(1, len(text) // 4)


def schema_token_report(catalog: ToolCatalog) -> dict[str, Any]:
    """The baseline number of the savings story: what the schemas cost."""
    per_tool = []
    total = 0
    for tool in catalog.tools:
        tokens = count_tokens(tool.as_mcp_tool())
        total += tokens
        per_tool.append({"name": tool.name, "group": tool.group, "tokens": tokens})
    per_tool.sort(key=lambda item: item["tokens"], reverse=True)
    return {"total_tokens": total, "tool_count": len(catalog.tools), "tools": per_tool}


def make_curated_callable(spec: ToolSpec, services: Any) -> Callable[..., Any]:
    """Build the callable behind a curated tool."""
    name = spec.name

    def revenue_by_plan(date_from: str = "2000-01-01", date_to: str = "2999-12-31", granularity: str = "month") -> Any:
        return services.analytics.revenue_by_plan(date_from, date_to, granularity)

    def tickets_at_risk(threshold: int = 0, reference_date: str | None = None) -> Any:
        return services.analytics.tickets_at_risk(reference_date, threshold)

    def top_agents(date_from: str = "2000-01-01", date_to: str = "2999-12-31", limit: int = 10) -> Any:
        return services.analytics.top_agents(date_from, date_to, limit)

    def open_tickets_for_account(account_id: int, limit: int = 50) -> Any:
        page = services.tickets.list_tickets(account_id=account_id, status="open", limit=limit)
        return {"items": page.items, "next_cursor": page.next_cursor}

    def plan_usage_summary(account_id: int) -> Any:
        return services.analytics.plan_usage_summary(account_id)

    functions = {
        "revenue_by_plan": revenue_by_plan,
        "tickets_at_risk": tickets_at_risk,
        "top_agents": top_agents,
        "open_tickets_for_account": open_tickets_for_account,
        "plan_usage_summary": plan_usage_summary,
    }
    return functions[name]


def trace_tool_call(tool_name: str, group: str):
    """A span around one tool call, so the traces show the MCP layer too."""
    return span(f"mcp.tool.call {tool_name}", tool=tool_name, group=group)
