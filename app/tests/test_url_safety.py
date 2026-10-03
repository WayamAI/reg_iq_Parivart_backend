"""
app/ingestion/url_safety.py: deterministic, no real DNS resolution anywhere here (a
fake resolver is injected into every call).
"""

import pytest

from app.ingestion.url_safety import UnsafeUrlError, validate_outbound_url


def _resolver_returning(*ips):
    def _fake(hostname, port):
        return [(None, None, None, None, (ip, 0)) for ip in ips]
    return _fake


def _resolver_raising():
    import socket

    def _fake(hostname, port):
        raise socket.gaierror("name or service not known")
    return _fake


def test_accepts_a_public_address():
    resolved = validate_outbound_url(
        "https://example.com/feed.xml", resolver=_resolver_returning("93.184.216.34")
    )
    assert resolved.ip_addresses == ["93.184.216.34"]


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",  # loopback
        "10.0.0.1",  # private
        "172.16.0.5",  # private
        "192.168.1.1",  # private
        "169.254.169.254",  # link-local / cloud metadata
        "224.0.0.1",  # multicast
        "0.0.0.0",  # unspecified
        "::1",  # loopback v6
        "fc00::1",  # unique local v6 (private)
        "fe80::1",  # link-local v6
    ],
)
async def test_rejects_every_blocked_ip_range(ip):
    with pytest.raises(UnsafeUrlError):
        validate_outbound_url("https://internal.example/feed.xml", resolver=_resolver_returning(ip))


def test_rejects_when_any_resolved_address_is_blocked():
    """A hostname resolving to BOTH a public and a private address must still be
    rejected -- one safe address does not make the host safe."""
    with pytest.raises(UnsafeUrlError):
        validate_outbound_url(
            "https://mixed.example/feed.xml",
            resolver=_resolver_returning("93.184.216.34", "127.0.0.1"),
        )


def test_rejects_unresolvable_host():
    with pytest.raises(UnsafeUrlError):
        validate_outbound_url("https://does-not-exist.invalid/feed.xml", resolver=_resolver_raising())


def test_rejects_non_http_scheme():
    with pytest.raises(UnsafeUrlError):
        validate_outbound_url("file:///etc/passwd", resolver=_resolver_returning("93.184.216.34"))


def test_rejects_ftp_scheme():
    with pytest.raises(UnsafeUrlError):
        validate_outbound_url("ftp://example.com/feed.xml", resolver=_resolver_returning("93.184.216.34"))


def test_rejects_url_with_no_hostname():
    with pytest.raises(UnsafeUrlError):
        validate_outbound_url("https:///feed.xml", resolver=_resolver_returning("93.184.216.34"))


def test_a_direct_private_ip_literal_is_still_rejected():
    """getaddrinfo on a literal IP returns that same IP, so this is covered by the
    same check as a hostname -- no special-case bypass for 'it's already an IP'."""
    with pytest.raises(UnsafeUrlError):
        validate_outbound_url(
            "http://169.254.169.254/latest/meta-data/",
            resolver=_resolver_returning("169.254.169.254"),
        )
