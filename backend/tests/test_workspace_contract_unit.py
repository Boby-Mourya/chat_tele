from copy import deepcopy

import pytest
from pydantic import ValidationError

from northstar_api.workspace_contract import WhiteLabelSettings, WhiteLabelWrite, WorkspacePreferences, safe_legacy_read


@pytest.mark.parametrize("key", ["dnsStatus", "dns_status", "customDomain", "custom_domain", "certificateStatus"])
def test_client_cannot_write_domain_proof_or_hostname(key):
    with pytest.raises(ValidationError):
        WhiteLabelWrite.model_validate({key: "verified"})


def test_legacy_brand_falls_back_without_mutating_database_values():
    stored = {"companyName": "Existing Academy", "primaryColor": "red", "logoDataUrl": "data:image/svg+xml;base64,PHN2Zz4=", "supportUrl": "javascript:alert(1)", "dnsStatus": "verified"}
    before = deepcopy(stored)
    warnings = []
    result = safe_legacy_read(WhiteLabelSettings, stored, warnings)
    assert stored == before
    assert result.company_name == "Existing Academy"
    assert result.logo_data_url == ""
    assert result.support_url == ""
    assert result.primary_color == "#0c0b0b"
    assert result.dns_status == "not-configured"
    assert len(warnings) == 4


def test_legacy_preferences_fall_back_and_preserve_valid_fields():
    warnings = []
    value = safe_legacy_read(WorkspacePreferences, {"timezone": "invalid", "defaultLanguage": "Hindi", "dateFormat": "garbage"}, warnings)
    assert value.timezone == "Asia/Calcutta"
    assert value.default_language == "Hindi"
    assert value.date_format == "DD/MM/YYYY"
    assert len(warnings) == 2


@pytest.mark.parametrize("url", ["javascript:alert(1)", "http://example.org", "https://user:password@example.org", "https:///path"])
def test_unsafe_support_links_rejected(url):
    with pytest.raises(ValidationError):
        WhiteLabelWrite(support_url=url)


def test_long_organization_name_supported():
    assert WhiteLabelWrite(company_name="A" * 160).company_name == "A" * 160
    with pytest.raises(ValidationError):
        WhiteLabelWrite(company_name="A" * 161)


def test_wrong_timezone_is_rejected_for_writes():
    with pytest.raises(ValidationError):
        WorkspacePreferences(timezone="../UTC")
