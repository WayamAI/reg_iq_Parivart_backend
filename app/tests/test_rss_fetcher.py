"""
app/ingestion/rss_fetcher.py: fully mocked transport, no real network access.

The one exception is test_real_client_construction_does_not_raise below, which
deliberately exercises fetch_feed's own httpx.AsyncClient construction (the
`client=None` path every test above bypasses by injecting a MockTransport
client) against a real loopback server -- that construction line is exactly
what broke in production (httpx.Timeout requires either a default or all four
phases set explicitly; the installed httpx version raises ValueError
otherwise), and no mocked-client test can catch a regression in it.
"""

import http.server
import threading

import httpx
import pytest

from app.ingestion.rss_fetcher import FeedFetchError, fetch_feed

FEED_BODY = b"<rss version=\"2.0\"><channel><item><title>x</title></channel></rss>"


def _client_for(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)


def _always_safe(url: str) -> None:
    """A stand-in url_validator that accepts everything -- these tests are about
    fetch behavior, not URL safety (covered separately in test_url_safety.py)."""
    return None


async def test_fetches_a_successful_response():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "application/rss+xml"}, content=FEED_BODY)

    body = await fetch_feed("https://example.com/feed.xml", client=_client_for(handler), url_validator=_always_safe)

    assert body == FEED_BODY


async def test_follows_a_redirect_once():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if str(request.url) == "https://example.com/old-feed.xml":
            return httpx.Response(302, headers={"location": "https://example.com/new-feed.xml"})
        return httpx.Response(200, headers={"content-type": "application/xml"}, content=FEED_BODY)

    body = await fetch_feed(
        "https://example.com/old-feed.xml", client=_client_for(handler), url_validator=_always_safe
    )

    assert body == FEED_BODY
    assert calls == ["https://example.com/old-feed.xml", "https://example.com/new-feed.xml"]


async def test_revalidates_each_redirect_hop():
    """The url_validator must be called again for the redirect target, not only the
    original URL -- a URL can be safe while its redirect target is not."""
    validated = []

    def validator(url: str) -> None:
        validated.append(url)

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == "https://example.com/start.xml":
            return httpx.Response(302, headers={"location": "https://example.com/end.xml"})
        return httpx.Response(200, headers={"content-type": "application/xml"}, content=FEED_BODY)

    await fetch_feed("https://example.com/start.xml", client=_client_for(handler), url_validator=validator)

    assert validated == ["https://example.com/start.xml", "https://example.com/end.xml"]


async def test_too_many_redirects_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": str(request.url) + "x"})

    with pytest.raises(FeedFetchError, match="too many redirects"):
        await fetch_feed(
            "https://example.com/loop",
            client=_client_for(handler),
            url_validator=_always_safe,
            max_redirects=2,
        )


async def test_non_success_status_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    with pytest.raises(FeedFetchError, match="404"):
        await fetch_feed("https://example.com/missing.xml", client=_client_for(handler), url_validator=_always_safe)


async def test_timeout_raises_feed_fetch_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    with pytest.raises(FeedFetchError, match="timed out"):
        await fetch_feed("https://example.com/slow.xml", client=_client_for(handler), url_validator=_always_safe)


async def test_connection_error_raises_feed_fetch_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(FeedFetchError, match="could not reach"):
        await fetch_feed("https://example.com/down.xml", client=_client_for(handler), url_validator=_always_safe)


async def test_oversized_response_is_rejected_during_download():
    big_body = b"x" * 1000

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "application/xml"}, content=big_body)

    with pytest.raises(FeedFetchError, match="exceeded"):
        await fetch_feed(
            "https://example.com/huge.xml",
            client=_client_for(handler),
            url_validator=_always_safe,
            max_response_bytes=100,
        )


async def test_unsafe_url_is_refused_before_any_request():
    def unsafe_validator(url: str) -> None:
        from app.ingestion.url_safety import UnsafeUrlError

        raise UnsafeUrlError("blocked for this test")

    called = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        called["count"] += 1
        return httpx.Response(200, content=FEED_BODY)

    with pytest.raises(FeedFetchError, match="unsafe URL"):
        await fetch_feed(
            "https://internal.example/feed.xml",
            client=_client_for(handler),
            url_validator=unsafe_validator,
        )
    assert called["count"] == 0


async def test_real_client_construction_does_not_raise():
    """Regression test for the production ValueError: without an injected
    `client=`, fetch_feed must build its own httpx.AsyncClient successfully. A
    real loopback HTTP server is used (not a mock) so this exercises the actual
    httpx.Timeout(...) construction; url_validator is relaxed only here, the
    same way other tests in this file relax it to isolate fetch behavior from
    URL-safety behavior (covered separately in test_url_safety.py)."""

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("content-type", "application/rss+xml")
            self.end_headers()
            self.wfile.write(FEED_BODY)

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        body = await fetch_feed(f"http://127.0.0.1:{port}/feed.xml", url_validator=_always_safe)
        assert body == FEED_BODY
    finally:
        server.shutdown()
        thread.join()
