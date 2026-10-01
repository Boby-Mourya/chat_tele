from __future__ import annotations

from northstar_api.modules.workspace.contracts import GeneralSettings, WorkspaceSettingsBundle


def test_general_settings_round_trip_uses_workspace_settings_contract() -> None:
    settings = GeneralSettings.model_validate(
        {
            "industry": "Education",
            "country": "India",
            "timeFormat": "12h",
            "currency": "INR",
            "weekStart": "monday",
            "description": "Admissions workspace",
            "workspaceIcon": "https://cdn.example.com/icon.png",
            "businessHours": {
                "enabled": True,
                "timezone": "Asia/Kolkata",
                "schedule": {
                    "monday": ["09:00-17:30"],
                    "friday": ["09:00-16:00"],
                },
            },
        }
    )

    payload = settings.model_dump(by_alias=True, mode="json")
    assert payload["timeFormat"] == "12h"
    assert payload["businessHours"]["timezone"] == "Asia/Kolkata"
    assert payload["businessHours"]["schedule"]["monday"] == ["09:00-17:30"]


def test_workspace_settings_bundle_keeps_general_settings_isolated() -> None:
    bundle = WorkspaceSettingsBundle()
    bundle.general.industry = "SaaS"
    bundle.general.business_hours.schedule = {"tuesday": ["10:00-18:00"]}

    stored = bundle.model_dump(by_alias=True, mode="json")
    restored = WorkspaceSettingsBundle.model_validate(stored)

    assert restored.general.industry == "SaaS"
    assert restored.general.business_hours.schedule == {"tuesday": ["10:00-18:00"]}
    assert restored.security.mfa_enforcement == "optional"
