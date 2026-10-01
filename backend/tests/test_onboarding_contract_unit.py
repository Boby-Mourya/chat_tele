from copy import deepcopy

import pytest
from pydantic import ValidationError

from northstar_api.onboarding_contract import BrandingChoiceSave, OrganizationProfileDraft, ProfileSave, STARTER_CATALOG, granted_starter_content


def profile(kind="institution"):
    values = {
        "organizationType": kind, "displayName": "Example Academy", "organizationSubtype": "Independent educator",
        "category": "Training", "country": "India", "timezone": "Asia/Kolkata", "preferredLanguage": "English",
        "contactName": "Example Owner", "contactEmail": "owner@example.com", "workspaceName": "Learning",
        "workspaceSlug": "learning", "teachingFocus": "Accounting", "programCategories": ["Accounting"],
        "learnerVolumeBand": "1–50", "description": "Customer support", "teamSizeBand": "2–10", "useCases": ["support"],
    }
    return values


@pytest.mark.parametrize("kind", ["institution", "business"])
def test_complete_profiles(kind):
    saved = ProfileSave(expectedRevision=0, profile=profile(kind), complete=True)
    assert saved.profile.missing_fields() == []


@pytest.mark.parametrize("field", ["displayName", "organizationSubtype", "category", "country", "contactName", "contactEmail", "workspaceName"])
def test_required_common_fields(field):
    values = profile()
    values[field] = ""
    with pytest.raises(ValidationError):
        ProfileSave(expectedRevision=0, profile=values, complete=True)


@pytest.mark.parametrize("kind,field,empty", [
    ("institution", "teachingFocus", ""), ("institution", "programCategories", []),
    ("institution", "learnerVolumeBand", ""), ("business", "description", ""),
    ("business", "teamSizeBand", ""), ("business", "useCases", []),
])
def test_required_branch_fields(kind, field, empty):
    values = profile(kind)
    values[field] = empty
    with pytest.raises(ValidationError):
        ProfileSave(expectedRevision=0, profile=values, complete=True)


@pytest.mark.parametrize("timezone", ["Mars/Colony", "../../etc/passwd", "", "India Standard Time"])
def test_invalid_timezones(timezone):
    with pytest.raises(ValidationError):
        OrganizationProfileDraft(timezone=timezone)


@pytest.mark.parametrize("slug", ["A-B", "-start", "end-", "a/b", "two words", "a", "---"])
def test_invalid_slug(slug):
    with pytest.raises(ValidationError):
        OrganizationProfileDraft(workspaceSlug=slug)


def test_draft_can_be_incomplete_without_unlocking_workspace():
    value = ProfileSave(expectedRevision=0, profile={}, complete=False)
    assert value.profile.missing_fields()
    assert value.complete is False


def test_normalization():
    value = OrganizationProfileDraft(contactEmail=" OWNER@EXAMPLE.COM ", programCategories=[" A ", "A", "", "B"])
    assert value.contact_email == "owner@example.com"
    assert value.program_categories == ["A", "B"]


@pytest.mark.parametrize("extra", [{"role": "owner"}, {"tenantId": "foreign"}, {"profileRequired": False}, {"dnsStatus": "verified"}])
def test_browser_cannot_set_authority_or_server_state(extra):
    with pytest.raises(ValidationError):
        ProfileSave(expectedRevision=0, profile={}, **extra)


@pytest.mark.parametrize("choice", ["customize", "keep_default", "deferred"])
def test_explicit_brand_choices(choice):
    assert BrandingChoiceSave(expectedRevision=2, choice=choice).choice == choice


@pytest.mark.parametrize("choice", ["unseen", "yes", "", "<script>"])
def test_invalid_choices(choice):
    with pytest.raises(ValidationError):
        BrandingChoiceSave(expectedRevision=0, choice=choice)


def test_grants_are_required_and_content_is_not_mutable_shared_state():
    before = deepcopy(STARTER_CATALOG)
    assert granted_starter_content([]) == []
    assert granted_starter_content(["private-tenant-source"]) == []
    items = granted_starter_content(["getting-started"])
    assert len(items) == 1 and items[0]["sample"] is True
    items[0]["content"] = "Changed locally"
    assert STARTER_CATALOG == before
