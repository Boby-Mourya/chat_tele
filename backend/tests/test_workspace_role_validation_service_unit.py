"""Section 23: role validation remains tenant/workspace scoped after extraction."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from northstar_api.modules.workspace import access
from northstar_api.modules.workspace.contracts import CustomRole, ResourceScope, RolesSettings
from northstar_api.modules.workspace.services.role_service import validate_workspace_role_assignments


class _ScopedSession:
    def __init__(self, *, members: tuple[UUID, ...] = (), agents: tuple[UUID, ...] = ()) -> None:
        self.members = members
        self.agents = agents
        self.queries: list[object] = []

    async def scalars(self, statement):
        self.queries.append(statement)
        sql = str(statement).lower()
        if "from workspace_memberships" in sql:
            assert "workspace_memberships.tenant_id" in sql
            assert "workspace_memberships.workspace_id" in sql
            return self.members
        if "from agents" in sql:
            assert "agents.tenant_id" in sql
            assert "agents.workspace_id" in sql
            assert "agents.deleted_at is null" in sql
            return self.agents
        raise AssertionError(f"Unexpected role validation query: {statement}")


def _principal():
    return SimpleNamespace(tenant_id=uuid4(), permissions=frozenset({"workspace.view"}))


def _role(*, role_id: str | None = None, permissions: list[str] | None = None) -> CustomRole:
    data: dict[str, object] = {
        "name": "Admissions",
        "permissions": permissions if permissions is not None else ["workspace.view"],
    }
    if role_id is not None:
        data["id"] = role_id
    return CustomRole(**data)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_duplicate_custom_role_identifiers_are_rejected_without_queries() -> None:
    existing = _role()
    session = _ScopedSession()
    with pytest.raises(HTTPException) as error:
        await validate_workspace_role_assignments(
            RolesSettings(custom_roles=[existing, _role(role_id=existing.id)]),
            _principal(),  # type: ignore[arg-type]
            session,  # type: ignore[arg-type]
            uuid4(),
        )
    assert error.value.status_code == 422
    assert session.queries == []


@pytest.mark.asyncio
async def test_role_cannot_delegate_permissions_the_actor_does_not_have() -> None:
    session = _ScopedSession()
    with pytest.raises(HTTPException) as error:
        await validate_workspace_role_assignments(
            RolesSettings(custom_roles=[_role(permissions=["members.manage"])]),
            _principal(),  # type: ignore[arg-type]
            session,  # type: ignore[arg-type]
            uuid4(),
        )
    assert error.value.status_code == 403
    assert "Cannot delegate permissions" in error.value.detail
    assert session.queries == []


@pytest.mark.asyncio
async def test_invalid_member_identifier_fails_before_any_database_query() -> None:
    session = _ScopedSession()
    role = _role()
    with pytest.raises(HTTPException) as error:
        await validate_workspace_role_assignments(
            RolesSettings(custom_roles=[role], member_role_ids={"not-a-uuid": [role.id]}),
            _principal(),  # type: ignore[arg-type]
            session,  # type: ignore[arg-type]
            uuid4(),
        )
    assert error.value.status_code == 422
    assert error.value.detail == "Invalid member identifier"
    assert session.queries == []


@pytest.mark.asyncio
async def test_role_assignment_rejects_member_from_other_workspace() -> None:
    session = _ScopedSession()
    role = _role()
    outside_member = uuid4()
    with pytest.raises(HTTPException) as error:
        await validate_workspace_role_assignments(
            RolesSettings(custom_roles=[role], member_role_ids={str(outside_member): [role.id]}),
            _principal(),  # type: ignore[arg-type]
            session,  # type: ignore[arg-type]
            uuid4(),
        )
    assert error.value.status_code == 422
    assert "outside this workspace" in error.value.detail
    assert len(session.queries) == 1


@pytest.mark.asyncio
async def test_role_assignment_rejects_unknown_role_id() -> None:
    member_id = uuid4()
    session = _ScopedSession(members=(member_id,))
    role = _role()
    with pytest.raises(HTTPException) as error:
        await validate_workspace_role_assignments(
            RolesSettings(custom_roles=[role], member_role_ids={str(member_id): ["missing"]}),
            _principal(),  # type: ignore[arg-type]
            session,  # type: ignore[arg-type]
            uuid4(),
        )
    assert error.value.status_code == 422
    assert error.value.detail == "A custom role assignment references an unknown role"
    assert len(session.queries) == 1


@pytest.mark.asyncio
async def test_role_agent_scope_rejects_agent_from_another_workspace() -> None:
    session = _ScopedSession()
    role = _role().model_copy(update={"resources": ResourceScope(selected={"agents": [str(uuid4())]})})
    with pytest.raises(HTTPException) as error:
        await validate_workspace_role_assignments(
            RolesSettings(custom_roles=[role]),
            _principal(),  # type: ignore[arg-type]
            session,  # type: ignore[arg-type]
            uuid4(),
        )
    assert error.value.status_code == 422
    assert "agent outside this workspace" in error.value.detail
    assert len(session.queries) == 1


@pytest.mark.asyncio
async def test_known_member_and_agent_are_validated_in_same_scoped_workspace() -> None:
    principal = _principal()
    workspace_id = uuid4()
    member_id = uuid4()
    agent_id = uuid4()
    role = _role().model_copy(update={"resources": ResourceScope(selected={"agents": [str(agent_id)]})})
    session = _ScopedSession(members=(member_id,), agents=(agent_id,))

    await validate_workspace_role_assignments(
        RolesSettings(custom_roles=[role], member_role_ids={str(member_id): [role.id]}),
        principal,  # type: ignore[arg-type]
        session,  # type: ignore[arg-type]
        workspace_id,
    )
    assert len(session.queries) == 2
    for statement in session.queries:
        params = set(statement.compile().params.values())
        assert principal.tenant_id in params
        assert workspace_id in params


@pytest.mark.asyncio
async def test_existing_access_validation_entry_point_delegates_to_role_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    principal = _principal()
    session = _ScopedSession()
    payload = RolesSettings()
    workspace_id = uuid4()
    calls: list[tuple[object, object, object, object]] = []

    async def validate(requested, actor, db_session, scoped_workspace):
        calls.append((requested, actor, db_session, scoped_workspace))

    monkeypatch.setattr(access, "validate_workspace_role_assignments", validate)
    await access._validate_roles(
        payload, principal, session, workspace_id  # type: ignore[arg-type]
    )
    assert calls == [(payload, principal, session, workspace_id)]
