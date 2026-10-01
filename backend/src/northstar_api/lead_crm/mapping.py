from __future__ import annotations

from datetime import date, datetime
from typing import Any

from northstar_api.lead_crm.models import LeadProfile
from northstar_api.models import Lead


def canonical_lead(lead: Lead, profile: LeadProfile) -> dict[str, Any]:
    return {
        "id": str(lead.id),
        "publicId": profile.public_id,
        "name": lead.name,
        "firstName": profile.first_name,
        "lastName": profile.last_name,
        "email": lead.email,
        "phone": lead.phone,
        "company": profile.company,
        "jobTitle": profile.job_title,
        "status": profile.lifecycle_status,
        "qualificationStatus": profile.qualification_status,
        "qualificationScore": profile.qualification_score,
        "qualificationReason": profile.qualification_reason,
        "source": {
            "channel": profile.source_channel,
            "provider": profile.source_provider,
            "connectionId": profile.source_connection_id,
            "externalId": profile.source_external_id,
            "campaign": profile.campaign,
            "campaignId": profile.campaign_id,
            "adId": profile.ad_id,
            "adsetId": profile.adset_id,
        },
        "utm": {
            "source": profile.utm_source,
            "medium": profile.utm_medium,
            "campaign": profile.utm_campaign,
            "term": profile.utm_term,
            "content": profile.utm_content,
        },
        "consentStatus": profile.consent_status,
        "customFields": dict(profile.custom_fields_json or {}),
        "createdAt": lead.created_at.isoformat() if lead.created_at else None,
        "updatedAt": lead.updated_at.isoformat() if lead.updated_at else None,
    }


def _resolve(value: Any, path: str) -> Any:
    current = value
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def _transform(value: Any, operation: str | None) -> Any:
    if operation is None:
        return value
    if operation in {"yyyy-mm-dd", "dd/mm/yyyy", "mm/dd/yyyy"} and value:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return parsed.strftime({"yyyy-mm-dd": "%Y-%m-%d", "dd/mm/yyyy": "%d/%m/%Y", "mm/dd/yyyy": "%m/%d/%Y"}[operation])
        except ValueError:
            return value
    if operation == "lower" and isinstance(value, str):
        return value.lower()
    if operation == "upper" and isinstance(value, str):
        return value.upper()
    if operation == "strip" and isinstance(value, str):
        return value.strip()
    if operation == "string" and value is not None:
        return str(value)
    if operation == "iso_datetime" and isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def build_mapped_payload(
    lead: Lead,
    profile: LeadProfile,
    mapping: dict[str, Any] | None,
    *,
    provider: str,
    configuration: dict[str, Any] | None = None,
) -> dict[str, Any]:
    canonical = canonical_lead(lead, profile)
    config = configuration or {}
    definition = mapping or {}
    output: dict[str, Any] = {}

    # Compact form: {"email": "Email", "phone": "Mobile"}.
    compact = definition.get("fields") if "fields" in definition else definition
    if isinstance(compact, dict):
        for source, target in compact.items():
            if not isinstance(target, str):
                continue
            value = _resolve(canonical, str(source))
            if value is not None and value != "":
                output[target] = value
    elif isinstance(compact, list):
        for rule in compact:
            if not isinstance(rule, dict) or not isinstance(rule.get("target"), str):
                continue
            if "constant" in rule:
                value = rule.get("constant")
            else:
                value = _resolve(canonical, str(rule.get("source") or ""))
                if (value is None or value == "") and "default" in rule:
                    value = rule.get("default")
            value = _transform(value, str(rule.get("transform")) if rule.get("transform") else None)
            value_map = rule.get("valueMap")
            if isinstance(value_map, dict) and value is not None:
                value = value_map.get(str(value), value)
            if value is not None and value != "":
                output[str(rule["target"])] = value

    # Sensible provider defaults keep a newly-created connection testable before
    # a tenant customizes the mapping. Explicit mappings always win.
    if provider == "zoho":
        defaults = {
            "First_Name": profile.first_name,
            "Last_Name": profile.last_name or lead.name or "Unknown",
            "Email": lead.email,
            "Mobile": lead.phone,
            "Company": profile.company or config.get("defaultCompany") or "Individual",
            "Description": profile.qualification_reason,
        }
        external_field = config.get("externalLeadIdField")
        if isinstance(external_field, str) and external_field:
            defaults[external_field] = profile.public_id
        for key, value in defaults.items():
            if key not in output and value not in {None, ""}:
                output[key] = value
    elif mapping is None:
        # Generic connectors receive a canonical object if no mapping is defined.
        output = canonical

    constants = definition.get("constants") if isinstance(definition, dict) else None
    if isinstance(constants, dict):
        for key, value in constants.items():
            output[str(key)] = value
    return output
