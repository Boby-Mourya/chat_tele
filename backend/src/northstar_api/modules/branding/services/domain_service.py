from __future__ import annotations

import asyncio
import ipaddress
import socket
from typing import Any

import httpx

from northstar_api.config import get_settings
from northstar_api.modules.workspace.contracts import DomainRecord


# A generic "failed" state can follow a DNS or worker-dispatch failure; it
# cannot establish domain ownership. A new DNS verification must succeed first.
TLS_ELIGIBLE_DOMAIN_STATUSES = frozenset({"verified", "certificate_pending"})


async def _dns_json(name: str, record_type: str) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=6.0, follow_redirects=False) as client:
            response = await client.get(
                "https://dns.google/resolve",
                params={"name": name, "type": record_type},
                headers={"Accept": "application/dns-json"},
            )
            response.raise_for_status()
            payload = response.json()
            return payload if isinstance(payload, dict) else {}
    except (httpx.HTTPError, ValueError):
        return {}


async def verify_domain_txt(domain: DomainRecord) -> bool:
    payload = await _dns_json(domain.verification_name, "TXT")
    answers = payload.get("Answer", [])
    if not isinstance(answers, list):
        return False
    expected = domain.verification_value
    for answer in answers:
        if not isinstance(answer, dict):
            continue
        value = str(answer.get("data", "")).strip().strip('"').replace('" "', "")
        if value == expected:
            return True
    return False


async def hostname_resolves_publicly(hostname: str) -> bool:
    def resolve() -> list[str]:
        try:
            return sorted(
                {
                    item[4][0]
                    for item in socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
                }
            )
        except OSError:
            return []

    addresses = await asyncio.to_thread(resolve)
    if not addresses:
        return False
    for value in addresses:
        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            return False
        if not address.is_global:
            return False
    return True


async def check_domain_tls(hostname: str) -> tuple[bool, str]:
    if not await hostname_resolves_publicly(hostname):
        return False, "Domain does not currently resolve only to public addresses"
    path = get_settings().app_api_prefix.rstrip("/") + "/branding/health"
    try:
        async with httpx.AsyncClient(timeout=7.0, follow_redirects=False) as client:
            response = await client.get(f"https://{hostname}{path}")
        if response.status_code == 204:
            return True, ""
        return False, f"HTTPS health endpoint returned {response.status_code}"
    except httpx.HTTPError as exc:
        return False, f"TLS/HTTPS is not ready ({type(exc).__name__})"


__all__ = [
    "TLS_ELIGIBLE_DOMAIN_STATUSES",
    "check_domain_tls",
    "hostname_resolves_publicly",
    "verify_domain_txt",
]
