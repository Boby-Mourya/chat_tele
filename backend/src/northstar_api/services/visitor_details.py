from __future__ import annotations

from ipaddress import ip_address, ip_network
from urllib.parse import parse_qs, urlsplit

from fastapi import Request

from northstar_api.config import get_settings


def capture_visitor_details(request: Request, payload) -> dict:
    details = payload.visitor_details.model_dump(exclude_none=True)
    # IP is server-observed, never accepted from widget JSON.
    details.pop("ip_address", None)
    peer = request.client.host if request.client else None
    trusted = [ip_network(item.strip()) for item in get_settings().visitor_trusted_proxy_cidrs.split(",") if item.strip()]
    try:
        address = ip_address(peer or "")
        chain = request.headers.get("x-forwarded-for", "").split(",")
        for raw in reversed(chain):
            if not any(address in network for network in trusted):
                break
            address = ip_address(raw.strip())
        details["ip_address"] = str(address)
    except ValueError:
        if peer:
            try:
                details["ip_address"] = str(ip_address(peer))
            except ValueError:
                pass
    if payload.page_url:
        page = urlsplit(payload.page_url)
        details.setdefault("page_slug", page.path[:500])
        query = parse_qs(page.query)
        for key in ("utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content"):
            if query.get(key):
                details[key] = query[key][0][:500 if key == "utm_content" else 240]
    return details


async def enrich_location(details: dict) -> dict:
    import httpx
    if not get_settings().visitor_geoip_enabled:
        return details
    try:
        address = ip_address(details.get("ip_address", ""))
        if not address.is_global:
            return details
        async with httpx.AsyncClient(timeout=2.0) as client:
            response = await client.get(f"https://ipwho.is/{address}", params={"fields": "success,city,region,country"})
            response.raise_for_status()
            data = response.json()
        if isinstance(data, dict) and data.get("success"):
            details["location"] = ", ".join(str(data[key]) for key in ("city", "region", "country") if data.get(key))[:500]
    except (ValueError, httpx.HTTPError):
        pass  # Enrichment must never prevent a visitor from starting a conversation.
    return details


async def update_linked_lead(session, conversation, changed_fields):
    from sqlalchemy import select

    from northstar_api.lead_crm.services import lead_domain_service
    from northstar_api.models import Lead
    from northstar_api.services.education_conversation_policy import education_source
    from northstar_api.services.outbox import enqueue_event
    lead = await session.scalar(select(Lead).where(
        Lead.conversation_id == conversation.id,
        ~education_source(Lead),
        Lead.tenant_id == conversation.tenant_id,
        Lead.workspace_id == conversation.workspace_id,
    ).with_for_update())
    if lead is None:
        return
    if "visitor_name" in changed_fields:
        lead.name = conversation.visitor_name
    if "visitor_email" in changed_fields:
        lead.email = conversation.visitor_email
    details = conversation.visitor_details or {}
    if "visitor_details" in changed_fields and "phone" in details:
        lead.phone = details["phone"]
    lead.fields_json = {**(lead.fields_json or {}), **details, "page_url": conversation.page_url}
    profile = await lead_domain_service.ensure_profile(session, lead=lead)
    profile.custom_fields_json = dict(lead.fields_json)
    for key in ("utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content"):
        setattr(profile, key, details.get(key))
    parts = (lead.name or "").split(None, 1)
    profile.first_name = parts[0][:100] if parts else None
    profile.last_name = parts[1][:100] if len(parts) > 1 else None
    from northstar_api.lead_crm.normalization import normalize_identity
    identity = normalize_identity(lead.email, lead.phone)
    profile.normalized_email = identity.email
    profile.normalized_phone = identity.phone
    for event_type in ("lead.updated.v1", "lead.crm.sync.requested.v1"):
        enqueue_event(session, tenant_id=lead.tenant_id, aggregate_type="lead", aggregate_id=lead.id,
            event_type=event_type, payload={"leadId": str(lead.id), "workspaceId": str(lead.workspace_id), "agentId": str(lead.agent_id), "reason": "lead_updated"})
