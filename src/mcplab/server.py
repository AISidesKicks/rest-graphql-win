"""The MCP server.

One MCPServer instance, mounted into the same FastAPI app at ``/mcp``. The
tools are generated from the live OpenAPI document plus the curated business
tools, and the exposure switch decides which groups are published.

The REST tools call the app in process, so a tool call really is a REST call
and the traces show the whole chain: MCP tool call, HTTP request, SQL query.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from config import EXPOSURE_CURATED, EXPOSURE_GRAPHQL, EXPOSURE_REST
from domain.errors import DomainError
from mcplab.catalog import ToolCatalog, ToolSpec, make_curated_callable, trace_tool_call


class ToolRunner:
    """Calls the lab from inside the process, over the real HTTP surface."""

    def __init__(self, app: FastAPI, services: Any) -> None:
        self.app = app
        self.services = services
        self._client: TestClient | None = None

    @property
    def client(self) -> TestClient:
        if self._client is None:
            self._client = TestClient(self.app)
        return self._client

    def call_rest(self, spec: ToolSpec, arguments: dict[str, Any]) -> Any:
        path = spec.path or "/"
        query: dict[str, Any] = {}
        body: dict[str, Any] = {}
        headers: dict[str, str] = {}
        for name, value in arguments.items():
            if value is None:
                continue
            location = spec.param_locations.get(name, "body")
            if location == "path":
                original = spec.original_names.get(name, name)
                path = path.replace(f"{{{original}}}", str(value))
            elif location == "query":
                query[name] = value
            elif location == "header":
                headers[spec.header_names.get(name, name)] = str(value)
            else:
                body[name] = value
        response = self.client.request(
            spec.method or "GET",
            path,
            params=query or None,
            json=body or None,
            headers=headers or None,
        )
        return _decode(response)

    def call_graphql(self, query: str, variables: dict[str, Any] | None = None) -> Any:
        payload: dict[str, Any] = {"query": query}
        if variables:
            payload["variables"] = variables
        response = self.client.post("/graphql", json=payload)
        return _decode(response)


def _decode(response: Any) -> Any:
    text = response.text
    try:
        return response.json()
    except Exception:
        return {"status_code": response.status_code, "body": text}


def build_tool_callable(
    spec: ToolSpec, runner: ToolRunner, services: Any
) -> Callable[..., Any]:
    """Build the function the MCP server and the sandbox both call."""

    if spec.kind == "curated":
        curated = make_curated_callable(spec, services)

        def call_curated(*args: Any, **kwargs: Any) -> Any:
            with trace_tool_call(spec.name, spec.group):
                try:
                    return curated(*args, **kwargs)
                except DomainError as exc:
                    return {"error": exc.to_payload()}

        return call_curated

    if spec.kind == "graphql":

        def call_graphql(*args: Any, **kwargs: Any) -> Any:
            with trace_tool_call(spec.name, spec.group):
                try:
                    if args and "query" not in kwargs:
                        kwargs["query"] = args[0]
                        args = args[1:]
                    return runner.call_graphql(*args, **kwargs)
                except DomainError as exc:
                    return {"error": exc.to_payload()}

        return call_graphql

    def call_rest(*args: Any, **kwargs: Any) -> Any:
        arguments: dict[str, Any] = dict(zip(spec.arguments, args, strict=False))
        arguments.update(kwargs)
        with trace_tool_call(spec.name, spec.group):
            try:
                return runner.call_rest(spec, arguments)
            except DomainError as exc:
                return {"error": exc.to_payload()}

    return call_rest


def build_catalog(app: FastAPI, services: Any, exposure: frozenset[str]) -> ToolCatalog:
    """Build the catalog from the live OpenAPI document of the app."""
    openapi = app.openapi()
    return ToolCatalog(openapi, services, exposure)


def create_mcp_server(
    app: FastAPI,
    services: Any,
    exposure: frozenset[str],
) -> tuple[MCPServer, ToolCatalog, ToolRunner]:
    """Create the MCP server with every exposed tool registered."""
    catalog = build_catalog(app, services, exposure)
    runner = ToolRunner(app, services)

    server = MCPServer(
        name="rest-graphql-lab",
        instructions=(
            "Tools for the REST and GraphQL lab. Every tool maps to one operation of the "
            "running application. Use the curated tools for the business questions, they "
            "already return the aggregated answer."
        ),
    )

    for spec in catalog.tools:
        function = build_tool_callable(spec, runner, services)
        server.add_tool(
            function,
            name=spec.name,
            description=spec.description,
        )
    return server, catalog, runner


def mount_mcp(
    app: FastAPI,
    services: Any,
    exposure: frozenset[str],
    path: str = "/mcp",
    settings: Any = None,
) -> tuple[MCPServer, ToolCatalog]:
    """Mount the MCP server into the FastAPI app."""
    server, catalog, runner = create_mcp_server(app, services, exposure)

    if settings is not None:
        from mcplab.codemode import CODE_MODE_INSTRUCTIONS, CodeModeRunner

        code_runner = CodeModeRunner(catalog, runner, services, settings)

        def exec_tool(code: str) -> str:
            """Run a Python program in the sandbox and return its output."""
            return code_runner.run(code).render()

        server.add_tool(
            exec_tool,
            name="exec",
            description=CODE_MODE_INSTRUCTIONS,
        )
        app.state.code_mode = code_runner

    mcp_app = server.streamable_http_app(
        streamable_http_path=path,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*", "testserver", "internal"],
            allowed_origins=["http://127.0.0.1:*", "http://localhost:*", "http://testserver"],
        ),
    )
    app.state.mcp_app = mcp_app
    app.state.mcp_catalog = catalog
    app.state.mcp_server = server
    app.state.mcp_runner = runner
    app.mount("/", mcp_app)
    return server, catalog


def describe_catalog(catalog: ToolCatalog) -> str:
    """A readable dump of the catalog, used by the tools script."""
    lines = []
    for group in (EXPOSURE_REST, EXPOSURE_GRAPHQL, EXPOSURE_CURATED):
        names = [tool.name for tool in catalog.tools if tool.group == group]
        if not names:
            continue
        lines.append(f"{group} ({len(names)})")
        for name in names:
            lines.append(f"  {name}")
    return "\n".join(lines)


def tool_json(payload: Any) -> str:
    return json.dumps(payload, default=str)
