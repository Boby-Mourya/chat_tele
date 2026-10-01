from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from northstar_api.services import safe_fetch


class UnsafeOutboundCRMURL(ValueError):
    pass


async def request_public(
    method: str,
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    params: Mapping[str, Any] | None = None,
    form_data: Mapping[str, str] | None = None,
    json_body: Any = None,
    content: bytes | None = None,
    timeout_seconds: float = 20,
) -> httpx.Response:
    """Send one non-redirecting request to a validated, DNS-pinned public target.

    This intentionally reuses the knowledge fetcher's resolution policy. The
    hostname is resolved once, all returned addresses must be public, and the
    actual TCP connection uses a validated IP while preserving the original
    Host header and TLS SNI/certificate hostname.

    Native CRM OAuth and API clients use the same helper as generic connectors,
    so configured provider domains cannot bypass the public-HTTPS boundary.
    """
    try:
        target = await safe_fetch._resolve_public_target(url)
    except safe_fetch.UnsafeURL as exc:
        raise UnsafeOutboundCRMURL(str(exc)) from exc
    if target.url.scheme != "https":
        raise UnsafeOutboundCRMURL("CRM destinations must use HTTPS")

    outgoing_headers = {str(key): str(value) for key, value in (headers or {}).items()}
    outgoing_headers["Host"] = target.host_header
    last_error: httpx.HTTPError | None = None
    for address in target.addresses:
        pinned_url = target.url.copy_with(host=address.compressed)
        extensions: dict[str, object] = {"sni_hostname": target.hostname}
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(timeout_seconds, connect=min(timeout_seconds, 8)),
                follow_redirects=False,
                trust_env=False,
                transport=safe_fetch._new_transport(),
            ) as client:
                return await client.request(
                    method.upper(),
                    pinned_url,
                    headers=outgoing_headers,
                    params=params,
                    data=form_data,
                    json=json_body,
                    content=content,
                    extensions=extensions,
                )
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    raise UnsafeOutboundCRMURL("CRM destination had no validated address")
