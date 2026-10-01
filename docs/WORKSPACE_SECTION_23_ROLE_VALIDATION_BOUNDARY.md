# Section 23 — Workspace custom-role validation boundary

Scope: Workspace only. This is additive to the existing `WORKSPACE_SECTION_23_API_COMPATIBILITY.md`; it does not change the teammate-owned sections 1–22, invitations, WhatsApp, or Super Admin.

## Existing production pipeline retained

`PATCH /workspace/settings/roles` still requires `roles.manage`, loads the tenant- and membership-scoped Workspace, and acquires the existing Workspace write lock. Its `_validate_roles` compatibility function now calls `services/role_service.validate_workspace_role_assignments`. The handler then calls the existing document update service, records the original before/after audit/outbox information, commits, and returns the same `RolesSettings` model. No route, migration, entitlement, permission name, SQLAlchemy mapping, storage format, or event contract was replaced.

The feature-owned validator preserves the existing rules and error responses:

- Custom role identifiers must be unique (422).
- Administrators cannot delegate a permission absent from their own effective permissions (403).
- Member identifiers must be UUIDs and belong to the caller's **tenant and Workspace** (422).
- Assigned custom role IDs must occur in the submitted role set (422).
- Selected agent identifiers must be UUIDs and resolve to non-deleted agents in the same **tenant and Workspace** (422).

The service also retains its previously committed guard against deleting a custom role while an existing team references it. The existing `access._validate_roles` name remains available to compatibility callers and test fixtures; the team validator and team write pipeline are unchanged.

## Regression coverage and limits

`backend/tests/test_workspace_role_validation_service_unit.py` checks duplicate IDs, blocked permission delegation, invalid/member-outside-Workspace IDs, unknown custom roles, selected agents outside the Workspace, a valid scoped member+agent request, and the old handler's delegation. `test_workspace_role_service_unit.py` separately covers team-reference deletion, persistence, and the original audit/commit boundary.

The tests are **committed, not verified passing**. From `backend/` run:

```bash
uv sync --all-groups --locked
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy src
uv run pytest tests/test_workspace_role_validation_service_unit.py tests/test_workspace_role_service_unit.py tests/test_workspace_production_router_registration_unit.py
```

Follow with executable full backend/frontend checks, PostgreSQL concurrent-write and tenant isolation tests, migration upgrade/rollback, and the applicable section-44 acceptance checks. Do not mark section 23 complete or merge drafts #132/#131 into `main` until those results pass.
