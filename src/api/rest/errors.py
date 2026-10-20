"""REST error handling.

The rule of the lab: the same domain error looks different on the wire
depending on the API style.

- REST answers with a status code and a small JSON body
- GraphQL answers with HTTP 200 and an ``errors`` array

The service layer raises one error type, this module decides how REST renders it.
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from domain.errors import DomainError

ETAG_PATTERN = re.compile(r'^(?:W/)?"?(\d+)"?$')


def error_body(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"error": {"code": code, "message": message}}
    if details:
        body["error"]["details"] = details
    return body


async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=error_body(exc.code, exc.message, exc.details))


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    details = {"errors": [_jsonable(item) for item in exc.errors()]}
    return JSONResponse(
        status_code=422,
        content=error_body("BAD_USER_INPUT", "the request payload is not valid", details),
    )


async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = "NOT_FOUND" if exc.status_code == 404 else "HTTP_ERROR"
    return JSONResponse(
        status_code=exc.status_code,
        content=error_body(code, str(exc.detail)),
    )


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def parse_if_match(value: str | None) -> int | None:
    """Read the expected version out of an If-Match header.

    ``"3"``, ``W/"3"`` and ``3`` all mean version 3.
    """
    if not value:
        return None
    match = ETAG_PATTERN.match(value.strip())
    if match is None:
        return None
    return int(match.group(1))


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(DomainError, domain_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_error_handler)
