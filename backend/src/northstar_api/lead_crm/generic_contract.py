"""Pure, configuration-bound contracts for generic REST destinations.

This validates syntax and credential origin, not DNS safety or remote business
completion. Network calls must still use the existing DNS-pinned safe transport.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import quote, unquote, urljoin, urlsplit

_HEADER_NAME = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+\Z")
_RESERVED_HEADERS = frozenset({
    "host", "connection", "content-length", "transfer-encoding", "proxy-authorization",
    "proxy-authenticate", "te", "trailer", "upgrade", "forwarded",
})
_CAPABILITIES = {
    "oauth": False, "schemaDiscovery": False, "create": False, "update": False,
    "upsert": False, "readBack": False, "inboundWebhooks": False, "webhookManagement": False,
}


def _url_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) > 8192:
        raise ValueError(f"{field} must be a bounded URL string")
    if any(ord(char) <= 32 or ord(char) == 127 for char in value) or "\\" in value:
        raise ValueError(f"{field} contains forbidden whitespace or separators")
    decoded = unquote(value)
    if any(ord(char) < 32 or ord(char) == 127 for char in decoded) or "\\" in decoded:
        raise ValueError(f"{field} contains encoded control characters or separators")
    return value


def _origin(value: str) -> tuple[str, str, int]:
    parsed = urlsplit(_url_text(value, "URL"))
    if parsed.scheme != "https" or not parsed.hostname or parsed.username is not None or parsed.password is not None:
        raise ValueError("Generic CRM requires HTTPS without embedded credentials")
    try:
        hostname = parsed.hostname.encode("idna").decode("ascii").lower()
        port = 443 if parsed.port is None else parsed.port
    except (UnicodeError, ValueError) as exc:
        raise ValueError("Generic CRM hostname or port is invalid") from exc
    if not 1 <= port <= 65535 or "%" in hostname:
        raise ValueError("Generic CRM hostname or port is invalid")
    return parsed.scheme, hostname, port


def assert_same_origin(configuration: Mapping[str, Any], url: str) -> None:
    base = _url_text(configuration.get("baseUrl"), "baseUrl")
    if _origin(base) != _origin(url):
        raise ValueError("Generic CRM paths must retain the configured credential origin")
    if urlsplit(url).fragment:
        raise ValueError("Generic CRM destinations cannot contain fragments")


def destination_url(
    configuration: Mapping[str, Any],
    path_key: str,
    default_path: str = "",
    *,
    external_id: str | None = None,
) -> str:
    base = _url_text(configuration.get("baseUrl"), "baseUrl")
    _origin(base)
    base_parts = urlsplit(base)
    if base_parts.query or base_parts.fragment:
        raise ValueError("baseUrl cannot contain query parameters or fragments; use an operation path")
    raw_path = configuration.get(path_key)
    path = _url_text(default_path if raw_path is None else raw_path, path_key)
    parsed = urlsplit(path)
    if parsed.scheme or parsed.netloc or path.startswith("//") or parsed.fragment:
        raise ValueError(f"{path_key} must be a relative path without an authority or fragment")
    if any(segment in {".", ".."} for segment in unquote(parsed.path).split("/")):
        raise ValueError(f"{path_key} cannot contain dot segments")
    if external_id is not None:
        if not isinstance(external_id, str) or not external_id or len(external_id) > 1024:
            raise ValueError("External record ID must be a non-empty bounded string")
        if external_id in {".", ".."} or any(ord(char) < 32 or ord(char) == 127 for char in external_id):
            raise ValueError("External record ID contains invalid characters")
        if path.count("{id}") != 1:
            raise ValueError(f"{path_key} must contain exactly one {{id}} placeholder")
        path = path.replace("{id}", quote(external_id, safe=""))
    if "{" in path or "}" in path:
        raise ValueError(f"{path_key} contains an unresolved placeholder")
    # Preserve the repository's existing base-path-relative convention for /paths.
    url = urljoin(base.rstrip("/") + "/", path.lstrip("/"))
    assert_same_origin(configuration, url)
    return url


def validate_headers(headers: Mapping[str, Any]) -> dict[str, str]:
    if not isinstance(headers, Mapping):
        raise ValueError("headers must be an object")
    if len(headers) > 64:
        raise ValueError("Generic CRM has too many headers")
    result: dict[str, str] = {}
    names: set[str] = set()
    for name, value in headers.items():
        if not isinstance(name, str) or len(name) > 128 or not _HEADER_NAME.fullmatch(name):
            raise ValueError("Generic CRM header name is invalid")
        lowered = name.lower()
        if lowered in names or lowered in _RESERVED_HEADERS or lowered.startswith(("proxy-", "x-forwarded-")):
            raise ValueError("Generic CRM has a duplicate or reserved header")
        if not isinstance(value, str) or len(value) > 8192 or any(ord(char) < 32 or ord(char) >= 127 for char in value):
            raise ValueError("Generic CRM header value is invalid")
        names.add(lowered)
        result[name] = value
    return result


def request_options(configuration: Mapping[str, Any]) -> tuple[float, frozenset[int], str]:
    raw_timeout = configuration.get("timeoutSeconds", 15)
    if isinstance(raw_timeout, bool):
        raise ValueError("timeoutSeconds must be a finite number")
    try:
        timeout = float(raw_timeout)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("timeoutSeconds must be a finite number") from exc
    if not math.isfinite(timeout):
        raise ValueError("timeoutSeconds must be a finite number")
    codes = configuration.get("successStatusCodes", [200, 201, 202, 204])
    if not isinstance(codes, list) or not codes or len(codes) > 100:
        raise ValueError("successStatusCodes must be a non-empty list of HTTP 2xx codes")
    if any(type(code) is not int or not 200 <= code < 300 for code in codes):
        raise ValueError("successStatusCodes can only contain HTTP 2xx integer codes")
    header = configuration.get("idempotencyHeader") or "Idempotency-Key"
    if not isinstance(header, str):
        raise ValueError("idempotencyHeader must be a string")
    validate_headers({header: "validation"})
    if header.lower() in {"authorization", "cookie", "content-type", "accept"} or header.lower().startswith("x-northstar-"):
        raise ValueError("idempotencyHeader cannot overwrite authentication or signing headers")
    return min(max(timeout, 1), 60), frozenset(codes), header


def validate_configuration(configuration: Mapping[str, Any]) -> None:
    """Validate the complete configured contract without network I/O."""
    destination_url(configuration, "createPath", configuration.get("path") or "")
    _, _, idempotency_header = request_options(configuration)
    raw_headers = configuration.get("headers")
    headers = validate_headers({} if raw_headers is None else raw_headers)
    method = configuration.get("method") or "POST"
    if not isinstance(method, str) or method.upper() not in {"POST", "PUT", "PATCH"}:
        raise ValueError("Generic CRM create method must be POST, PUT or PATCH")
    auth = configuration.get("auth")
    auth = {} if auth is None else auth
    if not isinstance(auth, Mapping):
        raise ValueError("auth must be an object")
    auth_type = auth.get("type", "NONE")
    if not isinstance(auth_type, str) or auth_type.upper() not in {
        "NONE", "", "BEARER", "BASIC", "API_KEY_HEADER"
    }:
        raise ValueError("Unsupported generic authentication type")
    if auth_type.upper() in {"BEARER", "BASIC", "API_KEY_HEADER"}:
        name = (auth.get("name") or "X-API-Key") if auth_type.upper() == "API_KEY_HEADER" else "Authorization"
        if not isinstance(name, str):
            raise ValueError("Authentication header name must be a string")
        validate_headers({name: "validation"})
        if name.lower() in {idempotency_header.lower(), "content-type", "accept"} or name.lower().startswith("x-northstar-"):
            raise ValueError("Authentication header conflicts with request or signing headers")
        if name.lower() in {key.lower() for key in headers}:
            raise ValueError("Authentication must be configured in one place, not duplicated in headers")
    for key in ("updatePath", "getPath", "upsertPath", "healthPath"):
        if configuration.get(key):
            record_id = "contract-check" if key in {"updatePath", "getPath"} else None
            destination_url(configuration, key, external_id=record_id)
    identity_path = configuration.get("externalIdPath")
    if identity_path is not None and (not isinstance(identity_path, str) or len(identity_path) > 512):
        raise ValueError("externalIdPath must be a bounded string")


def configured_capabilities(configuration: Mapping[str, Any]) -> dict[str, bool]:
    """Report configured operations, not the adapter's potential feature list.

    Invalid legacy drafts fail closed. These flags are not provider certification.
    """
    result = dict(_CAPABILITIES)
    try:
        validate_configuration(configuration)
    except (ValueError, TypeError):
        return result
    result["create"] = True
    for key, flag in (("updatePath", "update"), ("getPath", "readBack"), ("upsertPath", "upsert")):
        result[flag] = bool(configuration.get(key))
    return result
