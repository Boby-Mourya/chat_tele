import pytest
from northstar_api.entitlements import entitlement_for_plan, legacy_plan_aliases

@pytest.mark.parametrize("name", ["typo", "", "ENTERPRlSE", "custom-unapproved"])
def test_unknown_plans_never_grant_unlimited_capacity(name, monkeypatch):
    monkeypatch.delenv("NORTHSTAR_LEGACY_PLAN_ALIASES", raising=False)
    policy = entitlement_for_plan(name)
    assert policy.workspace_limit == 0
    assert not policy.crm_enabled and not policy.white_label_enabled and not policy.allowed_channels

@pytest.mark.parametrize("name", ["free", "starter", "professional"])
def test_core_customization_is_available_without_premium_brand_features(name):
    policy = entitlement_for_plan(name)
    assert policy.white_label_enabled
    assert not policy.custom_domain_enabled
    assert not policy.branded_email_enabled
    assert not policy.remove_platform_mark_enabled

@pytest.mark.parametrize("raw", ['[]', '{"enterprise":"free"}', '{"old":"typo"}', '{"old":42}'])
def test_legacy_aliases_cannot_override_catalog_or_chain(raw, monkeypatch):
    monkeypatch.setenv("NORTHSTAR_LEGACY_PLAN_ALIASES", raw)
    with pytest.raises(ValueError):
        legacy_plan_aliases()

def test_explicit_legacy_contract_mapping(monkeypatch):
    monkeypatch.setenv("NORTHSTAR_LEGACY_PLAN_ALIASES", '{"old-contract":"business"}')
    assert entitlement_for_plan("old-contract") == entitlement_for_plan("business")
