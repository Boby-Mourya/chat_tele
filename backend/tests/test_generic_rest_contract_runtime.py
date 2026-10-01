"""Exercise the real connector/schema; only outbound transport is mocked."""

from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from northstar_api.lead_crm.api_schemas import CRMConnectionCreate, CRMConnectionOut
from northstar_api.lead_crm.connectors import CRMConnectionContext, CRMError
from northstar_api.lead_crm.domain import CRMOperation, CRMProvider, NormalizedCRMErrorCode
from northstar_api.lead_crm.providers import generic

BASE = {"baseUrl": "https://crm.example/api", "createPath": "leads", "externalIdPath": "id"}


def context(configuration=None, credentials=None, provider=CRMProvider.GENERIC_REST):
    return CRMConnectionContext(
        tenant_id=uuid4(), connection_id=uuid4(), provider=provider,
        configuration=BASE if configuration is None else configuration,
        credentials={} if credentials is None else credentials,
    )


@pytest.fixture
def transport(monkeypatch):
    calls = []
    response = {"value": httpx.Response(201, json={"id": "lead-1"}, headers={"X-Request-ID": "request-1"})}

    async def send(method, url, **kwargs):
        calls.append({"method": method, "url": url, **kwargs})
        return response["value"]

    monkeypatch.setattr(generic, "request_public", send)
    return calls, response


@pytest.mark.asyncio
async def test_missing_upsert_never_sends_create(transport):
    calls, _ = transport
    with pytest.raises(CRMError) as error:
        await generic.GenericRESTConnector().upsert_lead(context(), {"name": "Synthetic"}, idempotency_key="one")
    assert error.value.code == NormalizedCRMErrorCode.CONFIGURATION_ERROR
    assert not calls


@pytest.mark.asyncio
async def test_explicit_create_preserves_operation_and_identity(transport):
    calls, _ = transport
    result = await generic.GenericRESTConnector().create_lead(context(), {"name": "Synthetic"}, idempotency_key="one")
    assert result.accepted and result.operation == CRMOperation.CREATE
    assert result.external_record_id == "lead-1" and result.provider_request_id == "request-1"
    assert len(calls) == 1 and calls[0]["headers"]["Idempotency-Key"] == "one"


@pytest.mark.asyncio
async def test_true_upsert_uses_only_its_endpoint(transport):
    calls, _ = transport
    result = await generic.GenericRESTConnector().upsert_lead(
        context({**BASE, "upsertPath": "leads/upsert"}), {"id": "synthetic"}, idempotency_key="one"
    )
    assert result.operation == CRMOperation.UPSERT and len(calls) == 1
    assert calls[0]["url"] == "https://crm.example/api/leads/upsert"


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["create_lead", "upsert_lead"])
async def test_non_json_202_is_acknowledged_without_fabricated_id(transport, method):
    calls, response = transport
    response["value"] = httpx.Response(202, content=b"accepted")
    result = await getattr(generic.GenericRESTConnector(), method)(
        context({**BASE, "upsertPath": "leads/upsert"}), {}, idempotency_key="one"
    )
    assert result.accepted and result.http_status == 202 and result.external_record_id is None
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [
    {"createPath": "https://other.example/steal"},
    {"headers": {"Host": "other.example"}},
    {"successStatusCodes": [500]},
    {"idempotencyHeader": "Authorization"},
    {"auth": {"type": "API_KEY_HEADER", "name": "Host"}},
    {"method": "DELETE"},
    {"headers": {"X-Key": "value\r\nInjected: yes"}},
])
async def test_invalid_configuration_never_reaches_transport(transport, change):
    calls, _ = transport
    with pytest.raises(CRMError):
        await generic.GenericRESTConnector().create_lead(
            context({**BASE, **change}, {"token": "synthetic", "api_key": "synthetic"}), {}, idempotency_key="one"
        )
    assert not calls


@pytest.mark.asyncio
async def test_direct_request_rechecks_credential_origin(transport):
    calls, _ = transport
    with pytest.raises(CRMError):
        await generic.GenericRESTConnector()._request(
            context({**BASE, "auth": {"type": "BEARER"}}, {"token": "synthetic"}),
            method="POST", url="https://other.example/steal", payload={},
        )
    assert not calls


@pytest.mark.asyncio
async def test_update_encodes_record_id(transport):
    calls, _ = transport
    result = await generic.GenericRESTConnector().update_lead(
        context({**BASE, "updatePath": "leads/{id}"}), "a/b?c=d", {}, idempotency_key="one"
    )
    assert result.operation == CRMOperation.UPDATE
    assert calls[0]["url"] == "https://crm.example/api/leads/a%2Fb%3Fc%3Dd"


@pytest.mark.asyncio
@pytest.mark.parametrize("status,code", [(301, "configuration_error"), (401, "authentication_error"), (429, "rate_limit_error"), (500, "provider_unavailable")])
async def test_non_success_remains_failure(transport, status, code):
    calls, response = transport
    response["value"] = httpx.Response(status, headers={"Retry-After": "10"})
    with pytest.raises(CRMError) as error:
        await generic.GenericRESTConnector().create_lead(context(), {}, idempotency_key="one")
    assert error.value.code.value == code and len(calls) == 1


@pytest.mark.asyncio
async def test_webhook_upsert_always_preserves_legacy_signature(transport, monkeypatch):
    calls, _ = transport
    monkeypatch.setattr(generic.time, "time", lambda: 1234567890)
    result = await generic.GenericWebhookConnector().upsert_lead(
        context(
            {"baseUrl": "https://crm.example", "path": "events", "upsertPath": "unsigned"},
            {"webhook_secret": "synthetic-secret"}, CRMProvider.GENERIC_WEBHOOK,
        ), {"name": "Synthetic"}, idempotency_key="event-one",
    )
    assert result.accepted and len(calls) == 1
    request = calls[0]
    assert request["url"] == "https://crm.example/events"
    digest = hmac.new(b"synthetic-secret", b"1234567890." + request["content"], hashlib.sha256).hexdigest()
    assert request["headers"]["X-Northstar-Signature"] == "sha256=" + digest
    assert request["headers"]["X-Northstar-Event-ID"] == "event-one"


def test_schema_rejects_invalid_config_before_connection_creation():
    with pytest.raises(ValidationError):
        CRMConnectionCreate(provider="generic_rest", name="Synthetic", configuration={**BASE, "upsertPath": "https://other.example"})


def test_empty_draft_is_allowed_but_credentials_require_contract():
    assert CRMConnectionCreate(provider="generic_rest", name="Synthetic").configuration == {}
    with pytest.raises(ValidationError):
        CRMConnectionCreate(provider="generic_rest", name="Synthetic", credentials={"token": "synthetic"})


def output(configuration, provider="generic_rest"):
    now = datetime.now(UTC)
    return CRMConnectionOut(
        id=uuid4(), public_id="crm_synthetic", provider=provider, name="Synthetic", environment="sandbox",
        region=None, status="draft", configuration=configuration,
        capabilities={"create": True, "upsert": True, "update": True, "readBack": True},
        last_authenticated_at=None, last_health_at=None, last_success_at=None, last_failure_at=None,
        last_error=None, created_at=now, updated_at=now,
    )


def test_api_read_recomputes_stale_capability_flags():
    value = output(BASE).model_dump()
    assert value["capabilities"]["create"]
    assert not value["capabilities"]["upsert"] and not value["capabilities"]["readBack"]
    assert not any(output({}).capabilities.values())


def test_native_provider_contract_is_not_changed():
    assert output({}, provider="zoho").capabilities["upsert"]
