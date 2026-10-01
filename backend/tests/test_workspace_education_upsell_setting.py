from httpx import AsyncClient


async def test_workspace_education_upsell_setting_cannot_be_enabled(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    current = await client.get("/api/v1/workspace", headers=auth_headers)
    assert current.status_code == 200, current.text
    before = current.json()
    assert before["educationCreateUpsellLeads"] is False

    enabled = await client.patch(
        "/api/v1/workspace",
        headers=auth_headers,
        json={"educationCreateUpsellLeads": True},
    )
    assert enabled.status_code == 409, enabled.text
    reloaded = await client.get("/api/v1/workspace", headers=auth_headers)
    assert reloaded.status_code == 200, reloaded.text
    assert reloaded.json()["educationCreateUpsellLeads"] is False
    assert reloaded.json()["name"] == before["name"]
    assert reloaded.json()["preferences"] == before["preferences"]

    disabled = await client.patch(
        "/api/v1/workspace",
        headers=auth_headers,
        json={"educationCreateUpsellLeads": False},
    )
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["educationCreateUpsellLeads"] is False
