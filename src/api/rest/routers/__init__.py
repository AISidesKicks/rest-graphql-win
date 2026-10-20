"""The REST routers."""

from __future__ import annotations

from api.rest.routers.analytics import router as analytics_router
from api.rest.routers.operational import router as operational_router

__all__ = ["analytics_router", "operational_router"]
