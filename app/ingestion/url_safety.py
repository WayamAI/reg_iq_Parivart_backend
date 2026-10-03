"""
SSRF-safe URL validation for outbound ingestion fetches.

Any URL this backend fetches on a user's behalf (a RegulatorySource.url, and every
redirect hop it leads to) must never be allowed to reach the host's own loopback
interface, its private network, link-local addresses, or a cloud metadata endpoint
(169.254.169.254 is covered by the link-local check, since that range is exactly where
every major cloud provider places its metadata service). A source URL is operator-
configured, not end-user-configured, but a compromised or malicious source record (or
one that redirects somewhere it shouldn't) must not become a way to probe or reach
internal infrastructure.
"""

import ipaddress
import socket
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlsplit

ALLOWED_SCHEMES = {"http", "https"}


class UnsafeUrlError(ValueError):
    """Raised when a URL (or a redirect target) resolves somewhere it must not."""


@dataclass
class ResolvedHost:
    hostname: str
    ip_addresses: list[str]


def _is_blocked_ip(ip_str: str) -> bool:
    ip = ipaddress.ip_address(ip_str)
    return (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def resolve_host(hostname: str, resolver: Callable = socket.getaddrinfo) -> ResolvedHost:
    """
    Resolve a hostname to every address it maps to. Raises UnsafeUrlError if resolution
    fails or yields no addresses -- an unresolvable host is never treated as "safe by
    default", it is refused.
    """
    try:
        infos = resolver(hostname, None)
    except socket.gaierror as exc:
        raise UnsafeUrlError(f"could not resolve host: {hostname}") from exc

    addresses = sorted({info[4][0] for info in infos})
    if not addresses:
        raise UnsafeUrlError(f"host resolved to no addresses: {hostname}")
    return ResolvedHost(hostname=hostname, ip_addresses=addresses)


def validate_outbound_url(url: str, resolver: Callable = socket.getaddrinfo) -> ResolvedHost:
    """
    Validate a URL is safe to fetch: http(s) scheme only, a hostname present, and
    EVERY address that hostname resolves to is a public, routable address -- not
    loopback, private, link-local, multicast, reserved, or unspecified.

    Must be called again for each redirect hop's target URL before following it; a
    URL that passes this check can still redirect somewhere unsafe, and following a
    redirect without re-validating it would defeat the whole point of this check.
    """
    parts = urlsplit(url)
    if parts.scheme not in ALLOWED_SCHEMES:
        raise UnsafeUrlError(f"unsupported URL scheme: {parts.scheme!r}")
    if not parts.hostname:
        raise UnsafeUrlError("URL has no hostname")

    resolved = resolve_host(parts.hostname, resolver=resolver)
    for ip_str in resolved.ip_addresses:
        if _is_blocked_ip(ip_str):
            raise UnsafeUrlError(
                f"host {parts.hostname!r} resolves to a disallowed address: {ip_str}"
            )
    return resolved
