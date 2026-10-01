from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from northstar_api.dependencies import _custom_role_context
from northstar_api.models import Role, Workspace, WorkspaceRole
from northstar_api.modules.workspace.api_key_scopes import permissions_for_api_key_scopes
from northstar_api.modules.workspace.contracts import (
    BusinessHours,
    CustomRole,
    DomainRecord,
    EmailTemplate,
    ExtendedBranding,
    NotificationSettings,
    ResourceScope,
    SecuritySettings,
    WorkspaceSettingsBundle,
    WorkspaceTeam,
)
from northstar_api.modules.workspace.email_branding import render_workspace_email
from northstar_api.modules.workspace.member_state import is_member_suspended, save_member_status
from northstar_api.modules.workspace.security_policy import (
    email_domain_allowed,
    required_password_length,
    validate_security_settings,
)
from northstar_api.modules.workspace.settings import _visible_bundle
from northstar_api.security import Principal
from northstar_api.services.notifications import _category_enabled


def _workspace(bundle: WorkspaceSettingsBundle) -> Workspace:
    return Workspace(
        tenant_id=uuid4(),
        name="Admissions",
        slug="admissions",
        settings_json={"workspaceSettingsV2": bundle.model_dump(by_alias=True, mode="json")},
    )


def _principal(*permissions: str) -> Principal:
    return Principal(
        user_id=uuid4(),
        tenant_id=uuid4(),
        role=Role.MEMBER,
        token_id="test-token",
        workspace_id=uuid4(),
        workspace_role=WorkspaceRole.VIEWER,
        permissions=frozenset(permissions),
    )


def test_settings_read_filters_unrelated_policy_sections() -> None:
    bundle = WorkspaceSettingsBundle()
    bundle.security.security_contact = "security@example.com"
    bundle.developer.rate_limit_per_minute = 321
    bundle.branding_draft.identity.company_name = "Acme Academy"
    bundle.roles.custom_roles = [
        CustomRole(name="Brand editor", permissions=["branding.edit"])
    ]

    branding_only = _visible_bundle(bundle, _principal("workspace.view", "branding.edit"))
    assert branding_only.branding_draft.identity.company_name == "Acme Academy"
    assert branding_only.security.security_contact is None
    assert branding_only.developer.rate_limit_per_minute != 321
    assert branding_only.roles.custom_roles == []

    roles_only = _visible_bundle(bundle, _principal("workspace.view", "roles.manage"))
    assert len(roles_only.roles.custom_roles) == 1
    assert roles_only.security.security_contact is None
    assert roles_only.branding_draft.identity.company_name != "Acme Academy"


def test_security_policy_rejects_invalid_network_and_enforces_email_domain_and_password() -> None:
    with pytest.raises(HTTPException) as invalid_network:
        validate_security_settings(SecuritySettings(ip_allowlist=["not-a-network"]))
    assert invalid_network.value.status_code == 422

    bundle = WorkspaceSettingsBundle()
    bundle.security.trusted_domains = ["example.com"]
    bundle.security.password_min_length = 18
    workspace = _workspace(bundle)

    assert email_domain_allowed(workspace, "person@example.com") is True
    assert email_domain_allowed(workspace, "person@dept.example.com") is True
    assert email_domain_allowed(workspace, "person@outside.test") is False
    assert required_password_length(workspace) == 18


def test_business_hours_and_custom_roles_are_validated_by_contract() -> None:
    hours = BusinessHours.model_validate(
        {"enabled": True, "timezone": "Asia/Kolkata", "schedule": {"MONDAY": ["09:00-17:30"]}}
    )
    assert hours.schedule == {"monday": ["09:00-17:30"]}

    with pytest.raises(ValidationError):
        BusinessHours.model_validate({"schedule": {"funday": ["09:00-17:00"]}})
    with pytest.raises(ValidationError):
        CustomRole(name="Unsafe", permissions=["platform.system.manage"])


def test_team_conversation_scope_uses_team_assignment_and_agent_boundaries() -> None:
    user_id = uuid4()
    team_agent_id = uuid4()
    outside_agent_id = uuid4()
    role_id = str(uuid4())
    bundle = WorkspaceSettingsBundle()
    bundle.roles.custom_roles = [
        CustomRole(
            id=role_id,
            name="Support team",
            permissions=["conversations.view"],
            resources=ResourceScope(conversation_scope="team"),
        )
    ]
    bundle.roles.member_role_ids = {str(user_id): [role_id]}
    team = WorkspaceTeam(
        name="Admissions",
        member_ids=[str(user_id)],
        agent_ids=[str(team_agent_id)],
    )
    bundle.teams.teams = [
        team,
        WorkspaceTeam(
            name="Other team",
            member_ids=[str(uuid4())],
            agent_ids=[str(outside_agent_id)],
        ),
    ]

    permissions, agent_scope, assigned_only, team_ids = _custom_role_context(
        _workspace(bundle), user_id
    )
    assert permissions == frozenset({"conversations.view"})
    assert agent_scope == frozenset({team_agent_id})
    assert assigned_only is False
    assert team_ids == frozenset({team.id})


def test_assigned_conversation_scope_is_enabled_only_when_it_is_the_effective_scope() -> None:
    user_id = uuid4()
    assigned_role_id = str(uuid4())
    team_role_id = str(uuid4())
    all_role_id = str(uuid4())

    bundle = WorkspaceSettingsBundle()
    bundle.roles.custom_roles = [
        CustomRole(
            id=assigned_role_id,
            name="Assigned only",
            permissions=["conversations.view"],
            resources=ResourceScope(conversation_scope="assigned"),
        ),
        CustomRole(
            id=team_role_id,
            name="Team scope",
            permissions=["conversations.view"],
            resources=ResourceScope(conversation_scope="team"),
        ),
        CustomRole(
            id=all_role_id,
            name="All conversations",
            permissions=["conversations.view"],
            resources=ResourceScope(conversation_scope="all"),
        ),
    ]

    bundle.roles.member_role_ids = {str(user_id): [assigned_role_id]}
    _, _, assigned_only, team_ids = _custom_role_context(_workspace(bundle), user_id)
    assert assigned_only is True
    assert team_ids == frozenset()

    team = WorkspaceTeam(name="Support", member_ids=[str(user_id)], agent_ids=[str(uuid4())])
    bundle.teams.teams = [team]
    bundle.roles.member_role_ids = {str(user_id): [assigned_role_id, team_role_id]}
    _, _, assigned_only, team_ids = _custom_role_context(_workspace(bundle), user_id)
    assert assigned_only is False
    assert team_ids == frozenset({team.id})

    bundle.roles.member_role_ids = {str(user_id): [assigned_role_id, team_role_id, all_role_id]}
    _, agent_scope, assigned_only, team_ids = _custom_role_context(_workspace(bundle), user_id)
    assert agent_scope is None
    assert assigned_only is False
    assert team_ids == frozenset()


def test_member_suspension_is_workspace_local_and_reversible() -> None:
    first_user = uuid4()
    second_user = uuid4()
    settings: dict[str, object] = {"unrelated": {"kept": True}}

    suspended = save_member_status(settings, first_user, "suspended")
    assert is_member_suspended(suspended, first_user) is True
    assert is_member_suspended(suspended, second_user) is False
    assert suspended["unrelated"] == {"kept": True}

    active = save_member_status(suspended, first_user, "active")
    assert is_member_suspended(active, first_user) is False


def test_api_key_scopes_expand_only_registered_service_permissions() -> None:
    permissions = permissions_for_api_key_scopes(["conversations:read", "analytics:read", "unknown"])
    assert permissions == frozenset({"conversations.view", "analytics.view"})


def test_notification_switches_control_runtime_categories() -> None:
    settings = NotificationSettings(
        member_changes=False,
        security_alerts=False,
        billing_alerts=True,
        channel_failures=False,
        integration_failures=True,
    )
    assert _category_enabled(settings, "member") is False
    assert _category_enabled(settings, "security") is False
    assert _category_enabled(settings, "channel") is False
    assert _category_enabled(settings, "billing") is True
    assert _category_enabled(settings, "crm") is True
    assert _category_enabled(settings, "education") is True


def test_published_email_renderer_uses_versioned_workspace_brand() -> None:
    bundle = WorkspaceSettingsBundle()
    published = ExtendedBranding()
    published.identity.company_name = "Acme Academy"
    published.identity.branded_emails = True
    published.email.sender_name = "Acme Support"
    published.email.footer = "© Acme Academy"
    published.email.templates["invitation"] = EmailTemplate(
        subject="Welcome to {{company_name}}",
        heading="Join {{workspace_name}}",
        body="You were invited as {{role}}.",
        button_label="Join now",
    )
    bundle.branding_published = published
    workspace = _workspace(bundle)

    rendered = render_workspace_email(
        workspace,
        "invitation",
        context={"role": "manager"},
        action_url="https://portal.example.com/workspace-invitation#token=secret",
        fallback_subject="Fallback",
        fallback_heading="Fallback",
        fallback_body="Fallback",
    )

    assert rendered.subject == "Welcome to Acme Academy"
    assert rendered.sender_name == "Acme Support"
    assert "Join Admissions" in rendered.text
    assert "manager" in rendered.text
    assert "© Acme Academy" in rendered.text
    assert "portal.example.com" in rendered.html


def test_domain_contract_normalizes_hostnames_and_rejects_urls() -> None:
    record = DomainRecord(
        hostname="Portal.Example.com.",
        verification_name="_northstar-verify.portal.example.com",
        verification_value="token",
    )
    assert record.hostname == "portal.example.com"
    with pytest.raises(ValidationError):
        DomainRecord(
            hostname="https://portal.example.com",
            verification_name="_northstar-verify.portal.example.com",
            verification_value="token",
        )
