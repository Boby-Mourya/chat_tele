from __future__ import annotations

from uuid import uuid4

import pytest
from starlette.requests import Request

from northstar_api.lead_crm.audit_models import IntegrationAuditEvent
from northstar_api.models import OutboxEvent, Workspace
from northstar_api.modules.branding.models import WorkspaceBrand
from northstar_api.modules.branding.services import brand_resolution_service
from northstar_api.modules.workspace.contracts import ExtendedBranding
from northstar_api.modules.workspace.events.administrative_events import (
    domain_event_name,
    emit_workspace_administrative_event,
)


class _CaptureSession:
    def __init__(self, scalar_value=None) -> None:
        self.added: list[object] = []
        self.scalar_value = scalar_value

    def add(self, value: object) -> None:
        self.added.append(value)

    async def scalar(self, _statement):
        return self.scalar_value


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "PATCH",
            "path": "/api/v1/workspace/settings/security",
            "headers": [(b"user-agent", b"workspace-test-agent")],
            "client": ("203.0.113.8", 54321),
            "scheme": "https",
            "server": ("example.test", 443),
            "query_string": b"",
        }
    )


def test_workspace_administrative_event_records_audit_and_typed_outbox() -> None:
    tenant_id = uuid4()
    workspace_id = uuid4()
    actor_id = uuid4()
    session = _CaptureSession()

    emit_workspace_administrative_event(
        session,  # type: ignore[arg-type]
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        actor_user_id=actor_id,
        action="workspace.brand.published",
        resource_type="workspace_brand_version",
        resource_id=f"{workspace_id}:4",
        fields=["version:4"],
        before={"token": "must-not-persist", "companyName": "Old"},
        after={"companyName": "New"},
        reason="Approved production brand",
        request=_request(),
    )

    audit = next(value for value in session.added if isinstance(value, IntegrationAuditEvent))
    event = next(value for value in session.added if isinstance(value, OutboxEvent))

    assert audit.tenant_id == tenant_id
    assert audit.workspace_id == workspace_id
    assert audit.actor_user_id == actor_id
    assert audit.entity_type == "workspace_brand_version"
    assert audit.before_json["token"] == "[REDACTED]"
    assert audit.after_json["companyName"] == "New"
    assert audit.metadata_json["reason"] == "Approved production brand"
    assert audit.ip_address == "203.0.113.8"
    assert audit.user_agent == "workspace-test-agent"
    assert event.event_type == "workspace.BrandPublished.v1"
    assert event.payload["workspaceId"] == str(workspace_id)
    assert event.payload["resourceType"] == "workspace_brand_version"


def test_domain_event_names_are_stable_capability_events() -> None:
    assert domain_event_name("workspace.settings.general.updated") == "WorkspaceUpdated"
    assert domain_event_name("workspace.brand.published") == "BrandPublished"
    assert domain_event_name("workspace.domain.verified") == "CustomDomainVerified"
    assert domain_event_name("workspace.unknown.changed") == "WorkspaceAdministrativeChanged"


@pytest.mark.asyncio
async def test_published_brand_resolution_prefers_normalized_storage(monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = Workspace(
        id=uuid4(),
        tenant_id=uuid4(),
        name="Admissions",
        slug="admissions",
        settings_json={},
        branding_json={},
    )
    branding = ExtendedBranding()
    branding.identity.company_name = "Normalized Academy"
    row = WorkspaceBrand(
        workspace_id=workspace.id,
        tenant_id=workspace.tenant_id,
        draft_json={},
        published_json=branding.model_dump(by_alias=True, mode="json"),
        published_version=7,
    )
    session = _CaptureSession(row)
    cached_versions: list[tuple[object, int, dict[str, object]]] = []
    cached_workspaces: list[tuple[object, dict[str, object]]] = []

    async def no_cache(*_args, **_kwargs):
        return None

    async def capture_version(workspace_id, version, payload):
        cached_versions.append((workspace_id, version, payload))

    async def capture_workspace(workspace_id, payload):
        cached_workspaces.append((workspace_id, payload))

    monkeypatch.setattr(brand_resolution_service, "cached_workspace_brand", no_cache)
    monkeypatch.setattr(brand_resolution_service, "cached_version_brand", no_cache)
    monkeypatch.setattr(brand_resolution_service, "cache_version_brand", capture_version)
    monkeypatch.setattr(brand_resolution_service, "cache_workspace_brand", capture_workspace)

    resolved, version = await brand_resolution_service.resolve_published_workspace_brand(
        session,  # type: ignore[arg-type]
        workspace,
    )

    assert resolved is not None
    assert resolved.identity.company_name == "Normalized Academy"
    assert version == 7
    assert cached_versions[0][1] == 7
    assert cached_workspaces[0][0] == workspace.id


def test_worker_queue_contract_is_operations_scoped() -> None:
    # The branding worker deliberately reuses the repository's existing durable
    # operations queue rather than introducing another queue technology.
    from northstar_api.workers.celery_app import celery_app

    routes = celery_app.conf.task_routes
    assert routes["northstar.verify_workspace_brand_domain"]["queue"] == "operations"
    assert routes["northstar.check_workspace_brand_tls"]["queue"] == "operations"
