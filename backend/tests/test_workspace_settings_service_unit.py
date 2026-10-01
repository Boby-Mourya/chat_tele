"""Section 23: feature-owned settings writes preserve legacy data and contracts."""

from __future__ import annotations

from uuid import uuid4

from northstar_api.models import Workspace, WorkspaceStatus
from northstar_api.modules.workspace.contracts import (
    DeveloperSettings,
    GeneralSettings,
    NotificationSettings,
    SecuritySettings,
    WorkspaceSettingsBundle,
)
from northstar_api.modules.workspace.services.settings_service import (
    update_developer_settings,
    update_general_settings,
    update_notification_settings,
    update_security_settings,
)
from northstar_api.modules.workspace.store import settings_document


def _workspace() -> Workspace:
    document = WorkspaceSettingsBundle()
    document.general.industry = "Education"
    return Workspace(
        id=uuid4(),
        tenant_id=uuid4(),
        name="Admissions",
        slug="admissions",
        status=WorkspaceStatus.ACTIVE,
        settings_json={
            "workspaceSettingsV2": document.model_dump(by_alias=True, mode="json"),
            "legacyFeature": {"enabled": True},
        },
        branding_json={},
    )


def test_general_service_retains_unrelated_settings_and_old_audit_snapshot() -> None:
    workspace = _workspace()
    before = update_general_settings(workspace, GeneralSettings(industry="Sales"))

    assert before["industry"] == "Education"
    assert settings_document(workspace).general.industry == "Sales"
    assert workspace.settings_json["legacyFeature"] == {"enabled": True}


def test_security_service_preserves_legacy_security_readers_and_other_sections() -> None:
    workspace = _workspace()
    before = update_security_settings(
        workspace,
        SecuritySettings(sensitive_data_masking=False, security_contact="security@example.com"),
    )

    assert before["sensitiveDataMasking"] is True
    assert workspace.settings_json["security"] == {
        "sensitiveDataMasking": False,
        "securityContact": "security@example.com",
    }
    assert settings_document(workspace).security.sensitive_data_masking is False
    assert settings_document(workspace).general.industry == "Education"
    assert workspace.settings_json["legacyFeature"] == {"enabled": True}


def test_notification_and_developer_services_preserve_each_other() -> None:
    workspace = _workspace()
    notification_before = update_notification_settings(
        workspace, NotificationSettings(weekly_digest=True)
    )
    developer_before = update_developer_settings(
        workspace, DeveloperSettings(sandbox_mode=True)
    )

    document = settings_document(workspace)
    assert notification_before["weeklyDigest"] is False
    assert developer_before["sandboxMode"] is False
    assert document.notifications.weekly_digest is True
    assert document.developer.sandbox_mode is True
    assert document.general.industry == "Education"
    assert workspace.settings_json["legacyFeature"] == {"enabled": True}
