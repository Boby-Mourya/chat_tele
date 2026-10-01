from dataclasses import FrozenInstanceError
from uuid import uuid4

import pytest
from pydantic import ValidationError

from northstar_api.starter_content_contract import (
    TemplateCloneRequest, approved_template, catalog_for, clone_fingerprint,
)


def request(**changes):
    return TemplateCloneRequest.model_validate({"idempotencyKey": str(uuid4()), "catalogVersion": 1,
                                                "name": "Sample support", **changes})


@pytest.mark.parametrize("extra", ["tenantId", "workspaceId", "role", "purpose", "instructions", "model", "status", "sourceAgentId"])
def test_caller_cannot_supply_scope_authority_or_recipe(extra):
    with pytest.raises(ValidationError):
        request(**{extra: "injected"})


@pytest.mark.parametrize("name", ["", " ", "x", "A" * 121, "ab\x00", "ab\ncd", "ab\u202ecd", "ab\u200bcd"])
def test_invalid_or_hidden_agent_names(name):
    with pytest.raises(ValidationError):
        request(name=name)


@pytest.mark.parametrize("version", [0, -1, True, "1", 1.5])
def test_catalog_version_is_a_positive_integer(version):
    with pytest.raises(ValidationError):
        request(catalogVersion=version)


def test_copies_are_only_offered_for_the_granted_approved_template():
    assert catalog_for([]) == []
    assert catalog_for(["another-tenant-source"]) == []
    items = catalog_for(["getting-started", "support-template", "education-boundaries"])
    assert [item["id"] for item in items if item["cloneable"]] == ["support-template"]
    assert all(item["sample"] is True for item in items)
    items[0]["content"] = "mutated response"
    assert catalog_for(["getting-started"])[0]["content"] != "mutated response"


@pytest.mark.parametrize("item,grants", [("support-template", []), ("education-boundaries", ["education-boundaries"]),
                                         ("private-source", ["private-source"])])
def test_tutorials_missing_grants_and_arbitrary_sources_cannot_clone(item, grants):
    with pytest.raises(LookupError):
        approved_template(item, 1, grants)


def test_stale_catalog_rejected_and_recipe_immutable():
    with pytest.raises(ValueError, match="catalog changed"):
        approved_template("support-template", 2, ["support-template"])
    value = approved_template("support-template", 1, ["support-template"])
    with pytest.raises(FrozenInstanceError):
        value.instructions = "mutated"  # type: ignore[misc]


def test_fingerprint_normalizes_names_but_binds_settings():
    value = approved_template("support-template", 1, ["support-template"])
    assert request(name=" Sample   support ").name == "Sample support"
    assert clone_fingerprint(value, request()) == clone_fingerprint(value, request(name=" Sample   support "))
    assert clone_fingerprint(value, request()) != clone_fingerprint(value, request(name="Another sample"))
