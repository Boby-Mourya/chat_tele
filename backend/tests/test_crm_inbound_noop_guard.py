from __future__ import annotations

from uuid import uuid4

from northstar_api.lead_crm.models import LeadProfile
from northstar_api.models import Lead
from northstar_api.workers.crm_webhook_consumer import _apply_field, _fanout_payload


def _lead_and_profile() -> tuple[Lead, LeadProfile]:
    tenant_id = uuid4()
    workspace_id = uuid4()
    agent_id = uuid4()
    lead_id = uuid4()
    lead = Lead(
        id=lead_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        agent_id=agent_id,
        name="Existing Name",
        email="existing@example.com",
        phone="+15550001111",
        status="new",
        consent=True,
        fields_json={},
    )
    profile = LeadProfile(
        tenant_id=tenant_id,
        lead_id=lead_id,
        lifecycle_status="new",
        qualification_status="pending",
        qualification_score=0,
        company="Existing Company",
        job_title="Existing Title",
        consent_status="granted",
        custom_fields_json={"tier": "gold", "region": "east"},
    )
    return lead, profile


def test_identical_supported_fields_are_noops_and_do_not_fan_out() -> None:
    lead, profile = _lead_and_profile()
    changed: dict[str, object] = {}
    values = {
        "status": "new",
        "name": "Existing Name",
        "email": "existing@example.com",
        "phone": "+15550001111",
        "company": "Existing Company",
        "jobTitle": "Existing Title",
        "custom.tier": "gold",
    }

    for field, value in values.items():
        if _apply_field(lead, profile, field, value):
            changed[field] = value

    assert changed == {}
    assert _fanout_payload(lead.id, uuid4(), changed) is None
    assert profile.custom_fields_json == {"tier": "gold", "region": "east"}


def test_real_inbound_changes_keep_existing_mutation_behavior() -> None:
    lead, profile = _lead_and_profile()
    changed: dict[str, object] = {}
    updates = {
        "status": "qualified",
        "name": "Updated Name",
        "email": "updated@example.com",
        "phone": "+15550002222",
        "company": "Updated Company",
        "jobTitle": "Updated Title",
        "custom.tier": "platinum",
    }

    for field, value in updates.items():
        if _apply_field(lead, profile, field, value):
            changed[field] = value

    assert changed == updates
    assert lead.status == "qualified"
    assert profile.lifecycle_status == "qualified"
    assert lead.name == "Updated Name"
    assert lead.email == "updated@example.com"
    assert lead.phone == "+15550002222"
    assert profile.company == "Updated Company"
    assert profile.job_title == "Updated Title"
    assert profile.custom_fields_json == {"tier": "platinum", "region": "east"}
    assert _fanout_payload(lead.id, uuid4(), changed) is not None


def test_status_truncation_compares_the_effective_persisted_value() -> None:
    lead, profile = _lead_and_profile()
    long_status = "x" * 80

    assert _apply_field(lead, profile, "status", long_status) is True
    assert lead.status == "x" * 40
    assert profile.lifecycle_status == "x" * 40
    assert _apply_field(lead, profile, "status", long_status) is False


def test_unknown_inbound_field_remains_ignored() -> None:
    lead, profile = _lead_and_profile()

    assert _apply_field(lead, profile, "unsupported", "value") is False
    assert lead.name == "Existing Name"
    assert profile.company == "Existing Company"
