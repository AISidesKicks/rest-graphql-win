"""The single ASGI app of the lab.

REST, GraphQL and MCP live in one process on one port. That is not a shortcut,
it is the point: the lab compares API styles, so the engine, the data and the
observability have to be identical for all of them.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from strawberry.fastapi import GraphQLRouter

from api.graphql.context import GraphQLContext, build_context
from api.graphql.schema import schema
from api.rest.errors import install_error_handlers
from api.rest.routers import analytics_router, operational_router
from config import Settings, load_settings
from data.duckdb_repo import DuckDbRepo
from data.sqlite_repo import SqliteRepo
from observability.tracing import setup_tracing, span
from services import Services


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the app. Everything hangs off this function."""
    settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        setup_tracing(
            service_name=settings.otel_service_name,
            traces_dir=settings.traces_dir,
            otlp_endpoint=settings.otlp_endpoint,
            enabled=settings.tracing_enabled,
        )
        repo = SqliteRepo(settings.oltp_path)
        repo.create_schema()
        duck = DuckDbRepo(settings.olap_path)
        services = Services(repo=repo, duck=duck)
        app.state.services = services
        app.state.settings = settings
        try:
            mcp_app = getattr(app.state, "mcp_app", None)
            if mcp_app is not None:
                async with mcp_app.router.lifespan_context(mcp_app):
                    yield
            else:
                yield
        finally:
            services.close()

    app = FastAPI(
        title="REST vs GraphQL vs MCP + code mode lab",
        description=(
            "One SaaS support and billing domain, four ways to reach it: REST over SQLite, "
            "GraphQL over SQLite, REST over DuckDB and GraphQL over DuckDB. The same MCP "
            "server and the same code mode sandbox sit on top."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings = settings

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def trace_requests(request: Request, call_next):
        with span(
            "http.server",
            method=request.method,
            path=request.url.path,
            query=request.url.query,
        ) as current:
            response = await call_next(request)
            current.set_attribute("http.status_code", response.status_code)
            return response

    install_error_handlers(app)
    app.include_router(operational_router)
    app.include_router(analytics_router)

    def get_services(request: Request) -> Services:
        return request.app.state.services

    async def get_context(
        request: Request, services: Services = Depends(get_services)
    ) -> GraphQLContext:
        return build_context(request, services)

    app.include_router(
        GraphQLRouter(schema, context_getter=get_context, graphql_ide="graphiql"),
        prefix="/graphql",
    )


    @app.get("/health", tags=["meta"], operation_id="rest_health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "mcp_exposure": sorted(settings.exposure_groups),
            "rest": "/api",
            "graphql": "/graphql",
            "mcp": settings.mcp_path,
        }

    _mount_mcp(app, settings)

    return app


def _mount_mcp(app: FastAPI, settings: Settings) -> None:
    """Mount the MCP server, after the services exist but before the lifespan runs."""
    from mcplab.server import mount_mcp

    class _LazyServices:
        """Resolves the services when the first tool call happens."""

        def __getattr__(self, item: str) -> Any:
            return getattr(app.state.services, item)

    mount_mcp(app, _LazyServices(), settings.exposure_groups, settings.mcp_path, settings)


app = create_app()
