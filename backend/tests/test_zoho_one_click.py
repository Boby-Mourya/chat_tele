from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from northstar_api.lead_crm.connectors import (
    CRMConnectionContext,
    CRMDeliveryResult,
    CRMFieldDefinition,
    crm_registry,
)
from northstar_api.lead_crm.domain import CRMOperation, CRMProvider
from northstar_api.lead_crm.models import CRMConnection
from northstar_api.services.zoho_one_click import build_default_zoho_mapping
from northstar_api.services.zoho_one_click_certification import certify_live_zoho
from northstar_api.zoho_platform import (
    ZohoPlatformConfigurationError,
    load_zoho_platform_configuration,
    resolve_zoho_data_center,
)


def test_platform_configuration_is_optional_and_never_contains_login_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ZOHO_CLIENT_ID", raising=False)
    monkeypatch.delenv("ZOHO_CLIENT_SECRET", raising=False)
    assert load_zoho_platform_configuration(required=False) is None


def test_platform_configuration_requires_client_pair(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ZOHO_CLIENT_ID", "client-id")
    monkeypatch.delenv("ZOHO_CLIENT_SECRET", raising=False)
    with pytest.raises(ZohoPlatformConfigurationError, match="configured together"):
        load_zoho_platform_configuration(required=True)


def test_platform_configuration_redacts_secret_and_builds_provider_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    test_secret = "unit-test-" + "credential-" + "value"
    regional_secret = "regional-" + "credential-" + "value"
    monkeypatch.setenv("ZOHO_CLIENT_ID", "client-id")
    monkeypatch.setenv("ZOHO_CLIENT_SECRET", test_secret)
    monkeypatch.setenv("ZOHO_CLIENT_SECRET_IN", regional_secret)
    monkeypatch.setenv("ZOHO_ACCOUNTS_URL", "https://accounts.zoho.com")
    monkeypatch.setenv("ZOHO_API_DOMAIN", "https://www.zohoapis.com")
    monkeypatch.setenv("ZOHO_OAUTH_FRONTEND_URL", "https://app.example.com/integrations")
    configuration = load_zoho_platform_configuration(required=True)
    assert configuration is not None
    assert test_secret not in repr(configuration)
    assert regional_secret not in repr(configuration)
    assert configuration.client_secret_for("in") == regional_secret
    assert configuration.client_secret_for("eu") == test_secret
    assert configuration.provider_configuration() == {
        "accountsUrl": "https://accounts.zoho.com",
        "apiDomain": "https://www.zohoapis.com",
        "apiVersion": "v8",
        "oauthScopes": [
            "ZohoCRM.modules.ALL",
            "ZohoCRM.settings.ALL",
            "ZohoCRM.org.READ",
        ],
        "duplicateCheckFields": ["Email"],
        "trigger": ["workflow"],
        "managedBy": "zoho-one-click",
        "multiDc": True,
    }


def test_zoho_data_center_uses_trusted_callback_location() -> None:
    assert resolve_zoho_data_center(
        location="in",
        accounts_server="https://accounts.zoho.in",
        default_accounts_url="https://accounts.zoho.com",
        default_api_domain="https://www.zohoapis.com",
    ) == (
        "https://accounts.zoho.in",
        "https://www.zohoapis.in",
        "in",
    )
    with pytest.raises(ZohoPlatformConfigurationError, match="untrusted accounts server"):
        resolve_zoho_data_center(
            location="in",
            accounts_server="https://attacker.example/zoho",
            default_accounts_url="https://accounts.zoho.com",
            default_api_domain="https://www.zohoapis.com",
        )
    with pytest.raises(ZohoPlatformConfigurationError, match="inconsistent"):
        resolve_zoho_data_center(
            location="eu",
            accounts_server="https://accounts.zoho.in",
            default_accounts_url="https://accounts.zoho.com",
            default_api_domain="https://www.zohoapis.com",
        )


def test_default_mapping_covers_standard_leads_and_required_custom_fields() -> None:
    fields = [
        CRMFieldDefinition("First_Name", "First Name", "text"),
        CRMFieldDefinition("Last_Name", "Last Name", "text", required=True, nullable=False),
        CRMFieldDefinition("Email", "Email", "email", unique=True),
        CRMFieldDefinition("Mobile", "Mobile", "phone"),
        CRMFieldDefinition("Company", "Company", "text", required=True, nullable=False),
        CRMFieldDefinition("Description", "Description", "textarea"),
        CRMFieldDefinition(
            "Territory_Type",
            "Territory Type",
            "picklist",
            required=True,
            nullable=False,
            custom=True,
            picklist_values=("Domestic", "International"),
        ),
        CRMFieldDefinition(
            "External_Lookup",
            "External Lookup",
            "lookup",
            required=True,
            nullable=False,
            custom=True,
        ),
    ]
    definition, unsupported = build_default_zoho_mapping(
        fields,
        certification_email="northstar@example.com",
    )
    assert definition["fields"] == {
        "firstName": "First_Name",
        "lastName": "Last_Name",
        "email": "Email",
        "phone": "Mobile",
        "company": "Company",
        "qualificationReason": "Description",
    }
    assert definition["constants"] == {"Territory_Type": "Domestic"}
    assert unsupported == ["External_Lookup"]


@pytest.mark.asyncio
async def test_live_certification_upserts_and_reads_back_without_workflow_triggers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class FakeZohoConnector:
        async def upsert_lead(
            self,
            context: CRMConnectionContext,
            payload: dict[str, Any],
            *,
            idempotency_key: str,
        ) -> CRMDeliveryResult:
            captured["context"] = context
            captured["payload"] = payload
            captured["idempotencyKey"] = idempotency_key
            return CRMDeliveryResult(
                accepted=True,
                operation=CRMOperation.UPSERT,
                external_record_id="zoho-lead-9001",
                http_status=200,
                provider_code="SUCCESS",
                provider_request_id="zoho-request-1",
                metadata={"action": "insert"},
            )

        async def get_lead(
            self,
            context: CRMConnectionContext,
            external_id: str,
        ) -> dict[str, Any]:
            assert external_id == "zoho-lead-9001"
            assert context.configuration["trigger"] == []
            return {
                "id": external_id,
                "Email": captured["payload"]["Email"],
                "Last_Name": captured["payload"]["Last_Name"],
                "Company": captured["payload"]["Company"],
            }

    connector = FakeZohoConnector()
    monkeypatch.setattr(crm_registry, "get", lambda provider: connector)
    connection = CRMConnection(
        id=uuid4(),
        tenant_id=uuid4(),
        provider=CRMProvider.ZOHO.value,
        name="Zoho one-click test",
        configuration_json={"trigger": ["workflow"]},
    )
    result = await certify_live_zoho(
        connection,
        credentials={"access_token": "test-token"},
        definition={"constants": {"Territory_Type": "Domestic"}},
    )

    assert captured["context"].configuration["trigger"] == []
    assert captured["payload"]["Territory_Type"] == "Domestic"
    assert captured["idempotencyKey"] == f"zoho-certification:{connection.id}"
    assert result == {
        "status": "verified",
        "externalRecordId": "zoho-lead-9001",
        "providerRequestId": "zoho-request-1",
        "providerCode": "SUCCESS",
        "action": "insert",
        "verifiedFields": ["Email", "Last_Name", "Company"],
        "verifiedAt": result["verifiedAt"],
        "certificationEmail": f"northstar.crm.cert.{connection.id.hex[:12]}@example.com",
    }
