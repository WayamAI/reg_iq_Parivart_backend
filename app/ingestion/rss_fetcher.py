"""
Safe HTTP retrieval of a feed or page body: timeouts, a bounded response size, and
manual redirect handling so every hop -- not just the original URL -- is revalidated by
app.ingestion.url_safety before being followed.

Despite the module name (kept for the RSS adapter that introduced it, to avoid
churning existing imports), `fetch_feed` is content-type agnostic via
`acceptable_content_type_markers` and is reused as-is by the HTML adapter
(app/ingestion/html_adapter.py) with `acceptable_content_type_markers=("html",)`. The
safety properties (SSRF validation, size bound, redirect re-validation, timeouts) are
identical regardless of what is being fetched.
"""

from typing import Callable, Optional

import httpx
import structlog

from app.ingestion.url_safety import UnsafeUrlError, validate_outbound_url

logger = structlog.get_logger()

DEFAULT_CONNECT_TIMEOUT_SECONDS = 10.0
DEFAULT_READ_TIMEOUT_SECONDS = 20.0
DEFAULT_MAX_RESPONSE_BYTES = 5 * 1024 * 1024  # 5 MB
DEFAULT_MAX_REDIRECTS = 5

ACCEPTABLE_CONTENT_TYPES = (
    "xml",  # covers text/xml, application/xml, application/rss+xml, application/atom+xml
)


class FeedFetchError(RuntimeError):
    """Raised for any fetch failure: unsafe URL, timeout, connection error, non-2xx
    status, oversized response, or too many redirects. Always a feed-level failure,
    never a crash -- the caller decides how to record it on the IngestionRun."""


async def fetch_feed(
    url: str,
    *,
    connect_timeout_seconds: float = DEFAULT_CONNECT_TIMEOUT_SECONDS,
    read_timeout_seconds: float = DEFAULT_READ_TIMEOUT_SECONDS,
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    max_redirects: int = DEFAULT_MAX_REDIRECTS,
    client: Optional[httpx.AsyncClient] = None,
    url_validator: Callable[[str], None] = validate_outbound_url,
    acceptable_content_type_markers: tuple = ACCEPTABLE_CONTENT_TYPES,
) -> bytes:
    """
    Fetch a feed's raw body, following redirects manually (httpx's automatic redirect
    following is disabled) so each hop's resolved address is validated before being
    followed -- a URL that is safe can still redirect somewhere that is not, and
    validating only the first URL would defeat the point of validating any of it.

    `client` lets a caller supply a pre-configured AsyncClient (e.g. to inject a
    MockTransport in tests); one is created and closed internally otherwise.
    """
    own_client = client is None
    if client is None:
        # httpx.Timeout requires either a default or all four phases set explicitly
        # (installed httpx>=0.28 raises ValueError otherwise) -- write/pool have no
        # separate setting here, so they're bounded by the same cap as read rather
        # than left unset.
        client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=connect_timeout_seconds,
                read=read_timeout_seconds,
                write=read_timeout_seconds,
                pool=read_timeout_seconds,
            ),
            follow_redirects=False,
        )

    try:
        current_url = url
        for hop in range(max_redirects + 1):
            try:
                url_validator(current_url)
            except UnsafeUrlError as exc:
                raise FeedFetchError(f"refusing unsafe URL: {exc}") from exc

            try:
                async with client.stream("GET", current_url) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise FeedFetchError("redirect response had no Location header")
                        current_url = str(httpx.URL(current_url).join(location))
                        continue

                    if response.status_code >= 400:
                        raise FeedFetchError(
                            f"feed returned HTTP {response.status_code} for {current_url}"
                        )

                    content_type = response.headers.get("content-type", "")
                    if not any(
                        marker in content_type.lower()
                        for marker in acceptable_content_type_markers
                    ):
                        logger.warning(
                            "ingestion_unexpected_content_type",
                            url=current_url,
                            content_type=content_type,
                        )
                        # Not a hard failure: some servers genuinely misreport
                        # content-type for an otherwise perfectly fine feed. The
                        # parser is the real gate -- it rejects non-XML content itself.

                    # Enforced DURING download, not after buffering the whole body --
                    # a server that lies about Content-Length (or omits it) cannot
                    # bypass the bound by simply sending more bytes than declared.
                    chunks = bytearray()
                    async for chunk in response.aiter_bytes():
                        chunks.extend(chunk)
                        if len(chunks) > max_response_bytes:
                            raise FeedFetchError(
                                f"feed response exceeded {max_response_bytes} bytes"
                            )
                    return bytes(chunks)
            except httpx.TimeoutException as exc:
                raise FeedFetchError(f"timed out fetching feed: {exc}") from exc
            except httpx.RequestError as exc:
                raise FeedFetchError(f"could not reach feed: {exc}") from exc

        raise FeedFetchError(f"too many redirects (> {max_redirects})")
    finally:
        if own_client:
            await client.aclose()
