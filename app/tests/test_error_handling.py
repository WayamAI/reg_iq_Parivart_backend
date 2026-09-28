"""
The frontend error contract.

Every failure mode must reach the browser as a readable HTTP response carrying CORS
headers, so JavaScript can tell an API error apart from the backend being unreachable:

    backend down            -> no HTTP response at all -> NETWORK_ERROR
    backend up, call failed -> HTTP status + JSON body + Access-Control-Allow-Origin

Before this change, an unhandled exception produced a 500 with no CORS headers (Starlette's
ServerErrorMiddleware sits outside CORSMiddleware), so the browser blocked it and the
frontend saw `TypeError: Failed to fetch` -- identical to the backend being down.

Failing routes are attached to the real application inside a fixture and removed
afterwards, so these exercise the production middleware stack without leaving a
deliberately broken endpoint behind.
"""

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import OperationalError

from app.core.config import settings
from app.core.errors import REQUEST_ID_HEADER
from app.main import app

ORIGIN = "http://localhost:8080"
CORS = {"Origin": ORIGIN}


@pytest.fixture
def failing_routes():
    """Temporarily mount routes that fail in specific ways, then remove them."""

    async def boom():
        raise RuntimeError("synthetic unhandled failure with a secret: hunter2")

    async def db_down():
        raise OperationalError(
            "SELECT * FROM users", {}, Exception("password authentication failed")
        )

    async def forbidden():
        raise HTTPException(status_code=403, detail="Not permitted")

    async def conflict():
        raise HTTPException(status_code=409, detail="Already exists")

    before = list(app.router.routes)
    app.add_api_route("/__test__/boom", boom, methods=["GET"], include_in_schema=False)
    app.add_api_route("/__test__/db", db_down, methods=["GET"], include_in_schema=False)
    app.add_api_route(
        "/__test__/forbidden", forbidden, methods=["GET"], include_in_schema=False
    )
    app.add_api_route(
        "/__test__/conflict", conflict, methods=["GET"], include_in_schema=False
    )
    yield
    app.router.routes = before


def _assert_cors_readable(response):
    """The browser will only expose this response to JS if the origin header matches."""
    assert response.headers.get("access-control-allow-origin") == ORIGIN
    assert response.headers.get("access-control-allow-credentials") == "true"


def _assert_error_envelope(response, expected_code: str):
    body = response.json()
    assert "error" in body, body
    assert body["error"]["code"] == expected_code
    assert body["error"]["message"]
    assert body["error"]["request_id"]
    assert body["error"]["request_id"] == response.headers[REQUEST_ID_HEADER]
    # FastAPI's existing `detail` convention is preserved for existing consumers.
    assert "detail" in body


# --- Configuration ---------------------------------------------------------------------

def test_frontend_origin_is_allowed_and_wildcard_is_not():
    origins = settings.cors_allow_origins
    assert ORIGIN in origins
    assert "*" not in origins


# --- Section 16: success ---------------------------------------------------------------

async def test_health_endpoints_succeed_with_cors(client):
    for path in ("/health", "/health/ready", "/health/live"):
        res = await client.get(path, headers=CORS)
        assert res.status_code == 200, path
        _assert_cors_readable(res)
        assert res.headers.get(REQUEST_ID_HEADER)


async def test_authenticated_success_has_cors(client, demo_org, auth_headers):
    for path in ("/api/v1/auth/me", "/api/v1/impact/", "/api/v1/reports/"):
        res = await client.get(path, headers={**auth_headers, **CORS})
        assert res.status_code == 200, f"{path} -> {res.text}"
        _assert_cors_readable(res)


async def test_preflight_is_accepted(client):
    res = await client.options(
        "/api/v1/impact/analyze",
        headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert res.status_code == 200
    assert res.headers["access-control-allow-origin"] == ORIGIN


async def test_request_id_header_is_exposed_to_javascript(client):
    """Without expose_headers the browser hides X-Request-ID from JS."""
    res = await client.get("/health", headers=CORS)
    exposed = res.headers.get("access-control-expose-headers", "")
    assert REQUEST_ID_HEADER.lower() in exposed.lower()


# --- Section 17/18/19: 4xx are readable ------------------------------------------------

async def test_422_validation_error_is_readable(client, demo_org, auth_headers):
    res = await client.post(
        "/api/v1/impact/analyze", json={}, headers={**auth_headers, **CORS}
    )
    assert res.status_code == 422
    _assert_cors_readable(res)
    _assert_error_envelope(res, "VALIDATION_ERROR")
    assert res.json()["error"]["fields"], "validation errors should name the fields"


async def test_401_unauthenticated_is_readable(client, demo_org):
    res = await client.get("/api/v1/impact/", headers=CORS)
    assert res.status_code == 401
    _assert_cors_readable(res)
    _assert_error_envelope(res, "UNAUTHORIZED")
    # The auth challenge header from the raising handler survives the envelope.
    assert res.headers.get("www-authenticate") == "Bearer"


async def test_401_bad_login_is_readable(client, demo_org):
    res = await client.post(
        "/api/v1/auth/login",
        data={"username": "admin@asterion.com", "password": "wrong"},
        headers=CORS,
    )
    assert res.status_code == 401
    _assert_cors_readable(res)
    _assert_error_envelope(res, "UNAUTHORIZED")


async def test_404_unknown_endpoint_is_readable(client):
    res = await client.get("/api/v1/does-not-exist", headers=CORS)
    assert res.status_code == 404
    _assert_cors_readable(res)
    _assert_error_envelope(res, "NOT_FOUND")


async def test_404_missing_resource_is_readable(client, demo_org, auth_headers):
    res = await client.get(
        "/api/v1/impact/00000000-0000-0000-0000-000000000000",
        headers={**auth_headers, **CORS},
    )
    assert res.status_code == 404
    _assert_cors_readable(res)
    _assert_error_envelope(res, "NOT_FOUND")


async def test_403_is_readable(client, failing_routes):
    res = await client.get("/__test__/forbidden", headers=CORS)
    assert res.status_code == 403
    _assert_cors_readable(res)
    _assert_error_envelope(res, "FORBIDDEN")


async def test_409_is_readable(client, failing_routes):
    res = await client.get("/__test__/conflict", headers=CORS)
    assert res.status_code == 409
    _assert_cors_readable(res)
    _assert_error_envelope(res, "CONFLICT")


# --- Section 20: the important case ----------------------------------------------------

async def test_unhandled_500_is_readable_and_leaks_nothing(client, failing_routes):
    res = await client.get("/__test__/boom", headers=CORS)

    # It stays a real 500 -- the failure is made readable, not hidden.
    assert res.status_code == 500
    _assert_cors_readable(res)
    _assert_error_envelope(res, "INTERNAL_SERVER_ERROR")

    raw = res.text
    assert "hunter2" not in raw  # no exception message
    assert "RuntimeError" not in raw  # no exception type
    assert "Traceback" not in raw
    assert "app/tests" not in raw  # no file paths
    assert res.json()["error"]["message"] == "An unexpected server error occurred."


async def test_database_error_is_a_controlled_500(client, failing_routes):
    res = await client.get("/__test__/db", headers=CORS)

    assert res.status_code == 500
    _assert_cors_readable(res)
    _assert_error_envelope(res, "DATABASE_ERROR")
    raw = res.text
    assert "password authentication failed" not in raw  # no credentials
    assert "SELECT" not in raw  # no SQL


async def test_500_without_an_origin_header_still_returns_json(client, failing_routes):
    """Non-browser clients (curl, server-to-server) get the same structured body."""
    res = await client.get("/__test__/boom")
    assert res.status_code == 500
    assert res.json()["error"]["code"] == "INTERNAL_SERVER_ERROR"


# --- Section 15: request ids -----------------------------------------------------------

async def test_every_response_carries_a_request_id(client, demo_org, auth_headers):
    responses = [
        await client.get("/health", headers=CORS),
        await client.get("/api/v1/impact/", headers=CORS),  # 401
        await client.get("/api/v1/does-not-exist", headers=CORS),  # 404
        await client.get("/api/v1/auth/me", headers={**auth_headers, **CORS}),  # 200
    ]
    ids = [r.headers.get(REQUEST_ID_HEADER) for r in responses]
    assert all(ids), ids
    assert len(set(ids)) == len(ids), "each request must get a distinct id"


async def test_client_supplied_request_id_is_preserved(client, failing_routes):
    """A frontend-generated id must survive so one trace spans both sides."""
    supplied = "frontend-trace-abc-123"
    res = await client.get(
        "/__test__/boom", headers={**CORS, REQUEST_ID_HEADER: supplied}
    )
    assert res.headers[REQUEST_ID_HEADER] == supplied
    assert res.json()["error"]["request_id"] == supplied


async def test_hostile_request_id_is_replaced(client):
    """An oversized or non-printable id must not be echoed into headers and logs."""
    for hostile in ("x" * 500, "bad\r\nInjected-Header: 1", "nul\x00byte"):
        res = await client.get("/health", headers={**CORS, REQUEST_ID_HEADER: hostile})
        returned = res.headers[REQUEST_ID_HEADER]
        assert returned != hostile
        assert len(returned) == 36  # a freshly generated uuid4
