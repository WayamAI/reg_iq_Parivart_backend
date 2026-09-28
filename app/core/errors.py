"""
Request correlation and CORS-safe error handling.

The problem this solves
-----------------------
Starlette builds its middleware stack as::

    ServerErrorMiddleware        <- handles unhandled exceptions
      -> user middleware         <- CORSMiddleware lives here
        -> ExceptionMiddleware   <- handles HTTPException
          -> router

An unhandled exception is caught by `ServerErrorMiddleware`, which sits *outside*
`CORSMiddleware`. Its 500 response therefore never passes back through CORS and carries no
`Access-Control-Allow-Origin`. The browser blocks it, and JavaScript sees
`TypeError: Failed to fetch` -- indistinguishable from the backend being down.

Registering `app.exception_handler(Exception)` does not fix this: FastAPI installs that
handler *on* `ServerErrorMiddleware`, still outside CORS.

The fix is `ExceptionHandlingMiddleware` below. It is registered as user middleware
*inner* to `CORSMiddleware`, so the response it returns travels back out through CORS and
is decorated normally. A real server failure stays a real 500 -- it is made readable, not
hidden.
"""

import uuid
from typing import Any, Callable, Dict, Optional

import structlog
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.security import PasswordTooLongError

logger = structlog.get_logger()

REQUEST_ID_HEADER = "X-Request-ID"

# Maximum length accepted for a client-supplied request id. Anything longer, or not
# printable ASCII, is replaced rather than echoed into logs and headers.
_MAX_REQUEST_ID_LENGTH = 128

# HTTP status -> stable machine-readable code. The frontend switches on these rather than
# parsing prose.
STATUS_CODE_NAMES: Dict[int, str] = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
    500: "INTERNAL_SERVER_ERROR",
    502: "UPSTREAM_ERROR",
    503: "SERVICE_UNAVAILABLE",
}

GENERIC_500_MESSAGE = "An unexpected server error occurred."

# Spelled numerically: Starlette deprecated HTTP_422_UNPROCESSABLE_ENTITY in favour of
# HTTP_422_UNPROCESSABLE_CONTENT, and the new name is not present in every supported
# version.
HTTP_422_UNPROCESSABLE = 422


def code_for_status(status_code: int) -> str:
    return STATUS_CODE_NAMES.get(status_code, f"HTTP_{status_code}")


def sanitize_request_id(raw: Optional[str]) -> str:
    """Accept a client-supplied correlation id, or mint one. Never trust it verbatim."""
    if raw:
        candidate = raw.strip()
        if (
            0 < len(candidate) <= _MAX_REQUEST_ID_LENGTH
            and candidate.isprintable()
            and candidate.isascii()
        ):
            return candidate
    return str(uuid.uuid4())


def get_request_id(request: Optional[Request]) -> str:
    if request is not None:
        existing = getattr(request.state, "request_id", None)
        if existing:
            return existing
    return str(uuid.uuid4())


def error_response(
    status_code: int,
    message: str,
    request_id: str,
    *,
    code: Optional[str] = None,
    detail: Any = None,
    extra: Optional[Dict[str, Any]] = None,
) -> JSONResponse:
    """
    Build the standard error body.

    `detail` is preserved at the top level because FastAPI's existing convention -- and
    everything already consuming this API -- reads `detail`. The `error` envelope is
    additive, giving clients a stable `code` and the `request_id` to quote in a bug report.
    """
    body: Dict[str, Any] = {
        "error": {
            "code": code or code_for_status(status_code),
            "message": message,
            "request_id": request_id,
        }
    }
    if extra:
        body["error"].update(extra)
    # Backwards-compatible alias.
    body["detail"] = detail if detail is not None else message
    return JSONResponse(
        status_code=status_code, content=body, headers={REQUEST_ID_HEADER: request_id}
    )


class RequestContextMiddleware(BaseHTTPMiddleware):
    """
    Assign every request a correlation id.

    Honours an inbound `X-Request-ID` so a trace can span frontend and backend, binds it
    into structlog's context so every log line during the request carries it, and echoes
    it on the response.
    """

    async def dispatch(self, request: Request, call_next: Callable):
        request_id = sanitize_request_id(request.headers.get(REQUEST_ID_HEADER))
        request.state.request_id = request_id

        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )
        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.unbind_contextvars("request_id", "method", "path")

        response.headers[REQUEST_ID_HEADER] = request_id
        return response


class ExceptionHandlingMiddleware(BaseHTTPMiddleware):
    """
    Catch anything the route handlers let escape and turn it into a readable 500.

    Must be registered *inner* to CORSMiddleware (that is, added to the app *before* it)
    so the response it produces is decorated with CORS headers on the way out.
    """

    async def dispatch(self, request: Request, call_next: Callable):
        try:
            return await call_next(request)
        except StarletteHTTPException:
            # Deliberate HTTP errors are handled by the registered handlers, which run
            # inside this middleware. Re-raise so they keep their status and body.
            raise
        except PasswordTooLongError as exc:
            request_id = get_request_id(request)
            logger.warning("password_too_long", request_id=request_id)
            return error_response(
                HTTP_422_UNPROCESSABLE, str(exc), request_id
            )
        except SQLAlchemyError as exc:
            request_id = get_request_id(request)
            # Full detail server-side only: SQL and driver messages can carry table
            # structure, connection strings and row values.
            logger.exception(
                "database_error", request_id=request_id, error_type=type(exc).__name__
            )
            return error_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                GENERIC_500_MESSAGE,
                request_id,
                code="DATABASE_ERROR",
            )
        except Exception as exc:  # noqa: BLE001 - this is the backstop
            request_id = get_request_id(request)
            logger.exception(
                "unhandled_exception",
                request_id=request_id,
                error_type=type(exc).__name__,
            )
            # The client gets a fixed message. Stack traces, exception text, secrets and
            # credentials stay in the server log, keyed by request_id.
            return error_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR, GENERIC_500_MESSAGE, request_id
            )


def register_exception_handlers(app: FastAPI) -> None:
    """Give deliberate HTTP errors the same envelope and the same request id."""

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        request_id = get_request_id(request)
        message = exc.detail if isinstance(exc.detail, str) else "Request failed"
        response = error_response(
            exc.status_code, message, request_id, detail=exc.detail
        )
        # Preserve WWW-Authenticate and friends from the raising handler.
        for key, value in (exc.headers or {}).items():
            response.headers[key] = value
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        request_id = get_request_id(request)
        # errors() can contain non-JSON-serialisable context; str() the exception values.
        errors = [
            {k: (v if k != "ctx" else {ck: str(cv) for ck, cv in (v or {}).items()})
             for k, v in err.items() if k != "input"}
            for err in exc.errors()
        ]
        return error_response(
            HTTP_422_UNPROCESSABLE,
            "Request validation failed",
            request_id,
            detail=errors,
            extra={"fields": errors},
        )

    @app.exception_handler(PasswordTooLongError)
    async def password_too_long_handler(request: Request, exc: PasswordTooLongError):
        request_id = get_request_id(request)
        return error_response(
            HTTP_422_UNPROCESSABLE, str(exc), request_id
        )
