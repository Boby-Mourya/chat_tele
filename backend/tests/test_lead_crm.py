from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest

from northstar_api.lead_crm.connectors import CRMError, crm_registry
from northstar_api.lead_crm.credentials import EncryptedDatabaseCredentialStore
from northstar_api.lead_crm.domain import (
    CRMDeliveryStatus,
    CRMOperation,
    CRMProvider,
    NormalizedCRMErrorCode,
    validate_delivery_transition,
)
from northstar_api.lead_crm.mapping import build_mapped_payload
from northstar_api.lead_crm.models import LeadProfile
from northstar_api.lead_crm.normalization import normalize_email, normalize_phone
from northstar_api.lead_crm.providers.generic import _classify_http, _extract_path
from northstar_api.lead_crm.providers.zoho import ZohoCRMConnector
from northstar_api.models import Lead


def test_identity_normalization_is_deterministic_without_country_guessing() -> None:
    assert normalize_email("  Example.User@Example.COM ") == "example.user@example.com"
    assert normalize_phone("+91 (98765) 43210") == "+919876543210"
    assert normalize_phone("98765 43210") == "9876543210"
    assert normalize_phone("---") is None


def test_delivery_state_machine_accepts_valid_and_rejects_invalid_transitions() -> None:
    validate_delivery_transition(CRMDeliveryStatus.CREATED, CRMDeliveryStatus.ROUTED)
    validate_delivery_transition(CRMDeliveryStatus.PROCESSING, CRMDeliveryStatus.ACKNOWLEDGED)
    validate_delivery_transition(CRMDeliveryStatus.ACKNOWLEDGED, CRMDeliveryStatus.VERIFYING)
    validate_delivery_transition(CRMDeliveryStatus.VERIFYING, CRMDeliveryStatus.VERIFIED)
    with pytest.raises(ValueError):
        validate_delivery_transition(CRMDeliveryStatus.CREATED, CRMDeliveryStatus.VERIFIED)
    with pytest.raises(ValueError):
        validate_delivery_transition(CRMDeliveryStatus.VERIFIED, CRMDeliveryStatus.RETRYING)


def test_credential_store_round_trip_and_wrong_key_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    store = EncryptedDatabaseCredentialStore()
    monkeypatch.setenv(store.ENV_KEY, "primary-secret")
    encrypted = store.encrypt({"access_token": "secret-token", "refresh_token": "refresh-token"})
    assert b"secret-token" not in encrypted
    assert store.decrypt(encrypted) == {"access_token": "secret-token", "refresh_token": "refresh-token"}
    monkeypatch.setenv(store.ENV_KEY, "different-secret")
    with pytest.raises(RuntimeError):
        store.decrypt(encrypted)


def test_default_registry_contains_initial_provider_connectors() -> None:
    assert crm_registry.get(CRMProvider.ZOHO).provider == CRMProvider.ZOHO
    assert crm_registry.get(CRMProvider.GENERIC_REST).provider == CRMProvider.GENERIC_REST
    assert crm_registry.get(CRMProvider.GENERIC_WEBHOOK).provider == CRMProvider.GENERIC_WEBHOOK


def test_generic_json_path_extraction() -> None:
    body = {"data": {"records": [{"id": "crm-123"}]}}
    assert _extract_path(body, "$.data.records.0.id") == "crm-123"
    assert _extract_path(body, "$.missing.id") is None


def test_generic_http_error_classification() -> None:
    rate = _classify_http(429, retry_after=17)
    assert rate.code == NormalizedCRMErrorCode.RATE_LIMIT_ERROR
    assert rate.retryable is True
    assert rate.retry_after_seconds == 17

    unavailable = _classify_http(503)
    assert unavailable.code == NormalizedCRMErrorCode.PROVIDER_UNAVAILABLE
    assert unavailable.retryable is True

    unauthorized = _classify_http(401)
    assert unauthorized.code == NormalizedCRMErrorCode.AUTHENTICATION_ERROR
    assert unauthorized.requires_reconnect is True

    validation = _classify_http(422)
    assert validation.code == NormalizedCRMErrorCode.VALIDATION_ERROR
    assert validation.retryable is False


def _lead_and_profile() -> tuple[Lead, LeadProfile]:
    tenant_id = uuid4()
    lead = Lead(
        id=uuid4(),
        tenant_id=tenant_id,
        agent_id=uuid4(),
        name="Rahul Sharma",
        email="rahul@example.com",
        phone="+919876543210",
        status="qualified",
        consent=True,
        fields_json={"product": "enterprise"},
    )
    lead.created_at = datetime.now(UTC)
    lead.updated_at = datetime.now(UTC)
    profile = LeadProfile(
        id=uuid4(),
        tenant_id=tenant_id,
        lead_id=lead.id,
        public_id="lead_123",
        first_name="Rahul",
        last_name="Sharma",
        normalized_email="rahul@example.com",
        normalized_phone="+919876543210",
        company="Example Pvt Ltd",
        lifecycle_status="qualified",
        qualification_status="qualified",
        qualification_score=92,
        qualification_reason="Enterprise purchase intent",
        consent_status="granted",
    )
    return lead, profile


def test_zoho_default_mapping_preserves_canonical_external_id() -> None:
    lead, profile = _lead_and_profile()
    payload = build_mapped_payload(
        lead,
        profile,
        {"fields": {"email": "Email", "phone": "Mobile"}},
        provider="zoho",
        configuration={"externalLeadIdField": "Application_Lead_ID"},
    )
    assert payload["Email"] == "rahul@example.com"
    assert payload["Mobile"] == "+919876543210"
    assert payload["First_Name"] == "Rahul"
    assert payload["Last_Name"] == "Sharma"
    assert payload["Company"] == "Example Pvt Ltd"
    assert payload["Application_Lead_ID"] == "lead_123"


def test_generic_mapping_supports_constant_default_transform_and_value_map() -> None:
    lead, profile = _lead_and_profile()
    payload = build_mapped_payload(
        lead,
        profile,
        {
            "fields": [
                {"source": "email", "target": "email", "transform": "lower"},
                {"source": "source.channel", "target": "source", "default": "unknown"},
                {"constant": "web", "target": "origin"},
                {"source": "status", "target": "state", "valueMap": {"qualified": "ready"}},
            ],
            "constants": {"tenantFlow": "lead-sync"},
        },
        provider="generic_rest",
    )
    assert payload == {
        "email": "rahul@example.com",
        "source": "unknown",
        "origin": "web",
        "state": "ready",
        "tenantFlow": "lead-sync",
    }


def test_zoho_ack_parser_requires_record_level_success() -> None:
    response = httpx.Response(
        200,
        headers={"X-ZOHO-REQUEST-ID": "req-1"},
        json={
            "data": [
                {
                    "status": "success",
                    "code": "SUCCESS",
                    "message": "record added",
                    "action": "insert",
                    "details": {"id": "5725000000012345"},
                }
            ]
        },
    )
    result = ZohoCRMConnector._parse_record_result(response, CRMOperation.UPSERT)
    assert result.accepted is True
    assert result.external_record_id == "5725000000012345"
    assert result.provider_request_id == "req-1"

    rejected = httpx.Response(
        207,
        json={"data": [{"status": "error", "code": "MANDATORY_NOT_FOUND", "message": "required"}]},
    )
    with pytest.raises(CRMError) as error:
        ZohoCRMConnector._parse_record_result(rejected, CRMOperation.UPSERT)
    assert error.value.code == NormalizedCRMErrorCode.VALIDATION_ERROR
