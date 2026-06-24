from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

import httpx

DEFAULT_MAX_REDIRECTS = 5
_DEFAULT_PORTS = {"http": 80, "https": 443}


class UnsafeUrlError(ValueError):
    """Raised when a URL is not safe to fetch server-side (SSRF guard)."""


def resolve_host_ips(host: str, port: int) -> list[str]:
    """Resolve a host to its IP addresses. Isolated so tests can stub it."""
    infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    return [str(info[4][0]) for info in infos]


def _address_is_blocked(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        # Unparseable address: treat as unsafe rather than fetch blindly.
        return True
    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    )


def assert_public_http_url(url: str) -> None:
    """Reject non-http(s) URLs and hosts that resolve to non-public addresses.

    Guards against SSRF: a user-supplied URL must not let the bot reach
    loopback, private LAN, or link-local (e.g. cloud metadata) endpoints.
    """
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise UnsafeUrlError("URL must be an absolute http or https URL")
    host = parts.hostname
    if not host:
        raise UnsafeUrlError("URL must include a host")
    port = parts.port or _DEFAULT_PORTS[parts.scheme]
    try:
        ips = resolve_host_ips(host, port)
    except (socket.gaierror, UnicodeError) as exc:
        raise UnsafeUrlError(f"could not resolve host {host!r}: {exc}") from exc
    if not ips:
        raise UnsafeUrlError(f"could not resolve host {host!r}")
    for ip in ips:
        if _address_is_blocked(ip):
            raise UnsafeUrlError(
                f"refusing to fetch {host!r}: resolves to non-public address {ip}"
            )


def get_public_url(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float,
    max_redirects: int = DEFAULT_MAX_REDIRECTS,
) -> httpx.Response:
    """GET ``url`` with redirects followed manually so every hop is SSRF-checked.

    httpx's built-in ``follow_redirects`` would re-validate nothing, letting a
    public URL redirect into the private network. We validate each hop instead.
    """
    current = url
    for _ in range(max_redirects + 1):
        assert_public_http_url(current)
        response = httpx.get(current, headers=headers, timeout=timeout, follow_redirects=False)
        if not response.is_redirect:
            return response
        location = response.headers.get("Location")
        if not location:
            return response
        current = str(response.url.join(location))
    raise UnsafeUrlError("too many redirects while fetching URL")
