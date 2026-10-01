from __future__ import annotations

from datetime import UTC, datetime
from ipaddress import ip_address, ip_network
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException, Request

from northstar_api.models import User, Workspace, WorkspaceRole

from .contracts import SecuritySettings, WorkspaceSettingsBundle


def security_settings(workspace: Workspace) -> SecuritySettings:
    raw = dict(workspace.settings_json or {}).get("workspaceSettingsV2", {})
    try:
        return WorkspaceSettingsBundle.model_validate(raw).security
    except (TypeError, ValueError):
        return SecuritySettings()


def validate_security_settings(value: SecuritySettings) -> None:
    for field_name, entries in (("IP allowlist", value.ip_allowlist), ("IP denylist", value.ip_denylist)):
        for entry in entries:
            try:
                ip_network(entry.strip(), strict=False)
            except ValueError:
                raise HTTPException(status_code=422, detail=f"{field_name} contains an invalid address or CIDR: {entry}") from None
    for domain in value.trusted_domains:
        normalized = domain.strip().lower().rstrip(".")
        if not normalized or "://" in normalized or "/" in normalized or " " in normalized or "." not in normalized:
            raise HTTPException(status_code=422, detail=f"Trusted domain is invalid: {domain}")


def normalize_trusted_domains(value: SecuritySettings) -> SecuritySettings:
    copied = value.model_copy(deep=True)
    copied.ip_allowlist = list(dict.fromkeys(entry.strip() for entry in copied.ip_allowlist if entry.strip()))
    copied.ip_denylist = list(dict.fromkeys(entry.strip() for entry in copied.ip_denylist if entry.strip()))
    copied.trusted_domains = list(dict.fromkeys(domain.strip().lower().rstrip(".") for domain in copied.trusted_domains if domain.strip()))
    return copied


def _request_ip(request: Request | None) -> str | None:
    if request is None or request.client is None:
        return None
    return request.client.host


def _in_networks(address: str, networks: list[str]) -> bool:
    try:
        candidate = ip_address(address)
    except ValueError:
        return False
    return any(candidate in ip_network(value, strict=False) for value in networks)


def enforce_network_security(workspace: Workspace, request: Request | None) -> None:
    policy = security_settings(workspace)
    address = _request_ip(request)
    if address and policy.ip_denylist and _in_networks(address, policy.ip_denylist):
        raise HTTPException(status_code=403, detail="This network is denied by the workspace security policy")
    if policy.ip_allowlist and (not address or not _in_networks(address, policy.ip_allowlist)):
        raise HTTPException(status_code=403, detail="This network is not allowed by the workspace security policy")


def enforce_request_security(
    workspace: Workspace,
    user: User,
    workspace_role: WorkspaceRole,
    token_payload: dict[str, Any],
    request: Request | None,
) -> None:
    policy = security_settings(workspace)
    enforce_network_security(workspace, request)
    requires_mfa = policy.mfa_enforcement == "all" or (
        policy.mfa_enforcement == "admins" and workspace_role == WorkspaceRole.ADMIN
    )
    if requires_mfa and not user.mfa_enabled:
        raise HTTPException(status_code=403, detail="This workspace requires MFA enrollment")

    issued_at = token_payload.get("iat")
    try:
        issued = datetime.fromtimestamp(float(issued_at), UTC)
    except (TypeError, ValueError, OSError):
        raise HTTPException(status_code=401, detail="Session issue time is invalid") from None
    age_seconds = (datetime.now(UTC) - issued).total_seconds()
    if age_seconds > policy.session_timeout_minutes * 60:
        raise HTTPException(status_code=401, detail="Workspace session timed out; sign in again")


def email_domain_allowed(workspace: Workspace, email: str) -> bool:
    trusted = security_settings(workspace).trusted_domains
    if not trusted:
        return True
    domain = email.rsplit("@", 1)[-1].strip().lower().rstrip(".")
    return any(domain == allowed or domain.endswith(f".{allowed}") for allowed in trusted)


def required_password_length(workspace: Workspace) -> int:
    return security_settings(workspace).password_min_length


def validate_business_timezone(value: str) -> None:
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError:
        raise HTTPException(status_code=422, detail=f"Unknown timezone: {value}") from None
