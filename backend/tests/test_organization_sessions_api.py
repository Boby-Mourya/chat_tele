"""Full-application regressions; run with the repository's normal conftest.

These tests intentionally substitute only the Redis transfer backend/rate limiter.
The application's real router, models, JWT helpers and SQLAlchemy session are used.
"""
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete

from northstar_api.database import SessionFactory
from northstar_api.models import Role, Tenant, TenantMembership
from northstar_api.routers import organization_sessions
from northstar_api.security import create_access_token, create_refresh_token, decode_token
from northstar_api.services.organization_session_transfer import REVOKE_UNDELIVERED_FAMILY, TRANSFER_REFRESH_FAMILY


class RecordingRedis:
    def __init__(self):
        self.values = {}

    async def exists(self, key):
        return int(key in self.values)

    async def eval(self, script, count, *args):
        if script == REVOKE_UNDELIVERED_FAMILY:
            assert count == 1
            key, token = args
            if self.values.get(key) == token:
                del self.values[key]
                return 1
            return 0
        assert script == TRANSFER_REFRESH_FAMILY and count == 3
        old_key, new_key, revoked_key, old_jti, new_jti, _ttl = args
        if self.values.get(old_key) != old_jti or new_key in self.values or revoked_key in self.values:
            return 0
        self.values[new_key] = new_jti
        del self.values[old_key]
        return 1


@pytest.fixture
async def organization_case(session_payload, monkeypatch):
    claims = decode_token(session_payload["accessToken"], "access")
    user_id, source_id = UUID(claims["sub"]), UUID(claims["tid"])
    target_id, foreign_id = uuid4(), uuid4()
    async with SessionFactory() as session:
        session.add_all([
            Tenant(id=target_id, name="Organization selection test", slug=f"org-{target_id.hex}", plan="free"),
            Tenant(id=foreign_id, name="Unrelated organization", slug=f"org-{foreign_id.hex}", plan="free"),
        ])
        await session.flush()
        session.add(TenantMembership(tenant_id=target_id, user_id=user_id, role=Role.BILLING_ADMIN))
        await session.commit()
    access, _ = create_access_token(user_id, source_id, Role(claims["role"]), credential_version=claims.get("cv", 0))
    refresh, _ = create_refresh_token(user_id, source_id, Role(claims["role"]), credential_version=claims.get("cv", 0))
    proof = decode_token(refresh, "refresh")
    store = RecordingRedis()
    store.values[f"northstar:refresh-family:{proof['fid']}"] = proof["jti"]
    monkeypatch.setattr(organization_sessions.redis_services, "client", store)

    async def allowed(*args, **kwargs):
        return SimpleNamespace(allowed=True, remaining=29, retry_after=0)

    monkeypatch.setattr(organization_sessions.redis_services, "check_rate_limit", allowed)
    return SimpleNamespace(
        target=target_id, foreign=foreign_id, user=user_id, store=store, proof=proof,
        headers={"Authorization": f"Bearer {access}", "Cookie": f"northstar_refresh={refresh}", "X-Workspace-ID": "ignored-at-org-boundary"},
    )


@pytest.mark.asyncio
async def test_organization_list_uses_real_memberships_not_workspace_header(client, organization_case):
    case = organization_case
    response = await client.get("/api/v1/me/organizations", headers=case.headers)
    assert response.status_code == 200, response.text
    ids = {item["id"] for item in response.json()["organizations"]}
    assert str(case.target) in ids and str(case.foreign) not in ids
    assert "no-store" in response.headers["Cache-Control"]


@pytest.mark.asyncio
async def test_billing_administrator_can_select_org_without_any_workspace(client, organization_case):
    case = organization_case
    response = await client.post("/api/v1/auth/select-organization", headers=case.headers, json={"organizationId": str(case.target)})
    assert response.status_code == 200, response.text
    claims = decode_token(response.json()["accessToken"], "access")
    assert claims["tid"] == str(case.target) and claims["role"] == "billing_admin"
    assert f"northstar:refresh-family:{case.proof['fid']}" not in case.store.values
    assert "HttpOnly" in response.headers["set-cookie"]


@pytest.mark.asyncio
async def test_selection_rechecks_removed_membership(client, organization_case):
    case = organization_case
    async with SessionFactory() as session:
        await session.execute(delete(TenantMembership).where(TenantMembership.tenant_id == case.target, TenantMembership.user_id == case.user))
        await session.commit()
    response = await client.post("/api/v1/auth/select-organization", headers=case.headers, json={"organizationId": str(case.target)})
    assert response.status_code == 403
    assert "set-cookie" not in response.headers


@pytest.mark.asyncio
async def test_organization_selection_rejects_foreign_membership(client, organization_case):
    case = organization_case
    response = await client.post("/api/v1/auth/select-organization", headers=case.headers, json={"organizationId": str(case.foreign)})
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_api_keys_cannot_select_an_organization(client, organization_case):
    response = await client.post("/api/v1/auth/select-organization", headers={"Authorization": "Bearer nsk_live_invalid-interactive-proof"}, json={"organizationId": str(organization_case.target)})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_selection_requires_refresh_proof(client, organization_case):
    case = organization_case
    headers = {**case.headers, "Cookie": ""}
    response = await client.post("/api/v1/auth/select-organization", headers=headers, json={"organizationId": str(case.target)})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_replay_does_not_revoke_the_winning_family(client, organization_case):
    case = organization_case
    first = await client.post("/api/v1/auth/select-organization", headers=case.headers, json={"organizationId": str(case.target)})
    assert first.status_code == 200, first.text
    winner = dict(case.store.values)
    second = await client.post("/api/v1/auth/select-organization", headers=case.headers, json={"organizationId": str(case.target)})
    assert second.status_code == 401 and case.store.values == winner


@pytest.mark.asyncio
async def test_browser_cannot_choose_the_new_organization_role(client, organization_case):
    case = organization_case
    response = await client.post("/api/v1/auth/select-organization", headers=case.headers, json={"organizationId": str(case.target), "role": "owner"})
    assert response.status_code == 422
