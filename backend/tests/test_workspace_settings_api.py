from __future__ import annotations

from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import delete

from northstar_api.database import SessionFactory
from northstar_api.models import Workspace, WorkspaceMembership


@pytest.mark.asyncio
async def test_workspace_settings_are_isolated_between_workspaces(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    current_response = await client.get("/api/v1/workspace", headers=auth_headers)
    assert current_response.status_code == 200, current_response.text
    first_workspace_id = current_response.json()["id"]
    first_headers = {**auth_headers, "X-Workspace-ID": first_workspace_id}

    settings_response = await client.get("/api/v1/workspace/settings", headers=first_headers)
    assert settings_response.status_code == 200, settings_response.text
    original_general = settings_response.json()["general"]
    updated_general = {
        **original_general,
        "industry": "Education",
        "country": "India",
        "timeFormat": "12h",
        "currency": "INR",
        "weekStart": "monday",
        "description": "Primary admissions workspace",
        "workspaceIcon": "",
        "businessHours": {
            "enabled": True,
            "timezone": "Asia/Kolkata",
            "schedule": {"monday": ["09:00-17:00"]},
        },
    }
    second_workspace_id: str | None = None
    try:
        updated = await client.patch(
            "/api/v1/workspace/settings/general",
            headers=first_headers,
            json=updated_general,
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["industry"] == "Education"

        created = await client.post(
            "/api/v1/workspaces",
            headers=auth_headers,
            json={
                "name": "Isolation Workspace",
                "slug": "isolation-workspace-settings-test",
                "timezone": "Asia/Kolkata",
                "defaultLanguage": "English",
                "dateFormat": "DD/MM/YYYY",
            },
        )
        assert created.status_code == 201, created.text
        second_workspace_id = created.json()["id"]
        second_headers = {**auth_headers, "X-Workspace-ID": second_workspace_id}

        second_settings = await client.get("/api/v1/workspace/settings", headers=second_headers)
        assert second_settings.status_code == 200, second_settings.text
        assert second_settings.json()["general"]["industry"] == ""
        assert second_settings.json()["general"]["description"] == ""

        first_again = await client.get("/api/v1/workspace/settings", headers=first_headers)
        assert first_again.status_code == 200, first_again.text
        assert first_again.json()["general"]["industry"] == "Education"
        assert first_again.json()["general"]["description"] == "Primary admissions workspace"
    finally:
        await client.patch(
            "/api/v1/workspace/settings/general",
            headers=first_headers,
            json=original_general,
        )
        if second_workspace_id is not None:
            workspace_id = UUID(second_workspace_id)
            async with SessionFactory() as session:
                await session.execute(delete(WorkspaceMembership).where(WorkspaceMembership.workspace_id == workspace_id))
                await session.execute(delete(Workspace).where(Workspace.id == workspace_id))
                await session.commit()
