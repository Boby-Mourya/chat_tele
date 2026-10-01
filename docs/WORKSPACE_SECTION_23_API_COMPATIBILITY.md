# Workspace section 23 — API, model, service boundaries and compatibility

This document covers only Workspace/branding feature boundaries. It describes committed code on the corrective branch of draft PR #132, based on the Workspace implementation branch of draft PR #131. Sections 24–26 (WhatsApp), 31 (Super Admin), and teammate sections 1–22 are excluded.

## Registration and compatibility rule

`northstar_api.routers` registers `modules.workspace.router` under the application's existing API prefix and global entitlement dependency. The Workspace aggregate keeps its `/workspace/settings` prefix. An existing path must be registered **exactly once** in the application's aggregate router. New canonical capability routers reuse the *same existing endpoint function*, FastAPI dependency annotations, HTTP method, response model and status code. The combined routers remain importable for legacy callers but are not additionally registered.

| Capability | Canonical API module | Existing path suffix / HTTP method |
| --- | --- | --- |
| Read settings and capabilities | `modules/workspace/api/workspace_settings_core.py` | `GET /`; `GET /capabilities` |
| Update general settings | `modules/workspace/api/workspace_general_settings.py` | `PATCH /general` |
| Workspace general metadata | `modules/workspace/general.py` | `GET /general/metadata` |
| Security settings | `modules/workspace/api/workspace_security.py` | `PATCH /security` |
| Notification settings | `modules/workspace/api/workspace_notifications.py` | `PATCH /notifications` |
| Developer settings | `modules/workspace/api/workspace_developer.py` | `PATCH /developer` |
| Member lifecycle | `modules/workspace/api/workspace_members.py` | Existing member routes (unchanged) |
| Roles | `modules/workspace/api/workspace_roles.py` | `PATCH /roles` |
| Teams | `modules/workspace/api/workspace_teams.py` | `PATCH /teams` |
| Dashboard settings | `modules/workspace/api/workspace_dashboard.py` | `PATCH /dashboard` |
| Brand read, runtime and draft | `modules/branding/api/brand_draft.py` | `GET /branding`; `GET /runtime-branding`; `PATCH /branding/draft` |
| Brand publication and rollback | `modules/branding/api/brand_versions.py` | `POST /branding/publish`; `POST /branding/rollback` |
| Custom domains | Existing `modules/workspace/domains.py`, exported by `modules/branding/api` | Existing `/domains` operations (unchanged) |
| Branded email preview and test | Existing `modules/workspace/email_routes.py`, exported by `modules/branding/api` | `POST /branding/email/preview`; `POST /branding/email/test` |

All suffixes above are relative to `/workspace/settings` and the existing application-wide API prefix. `modules/workspace/api/workspace_invitations.py` is an **opt-in import adapter**: invitation routes remain registered once by their existing owner; this branch does not change their handlers or teammate-owned files.

## Model boundaries without a schema change

The canonical `modules/workspace/models/` package now exposes these feature-owned modules, all of which **re-export the existing Python class objects** rather than declaring new SQLAlchemy mappings:

| Canonical module | Original types | Existing persistence |
| --- | --- | --- |
| `models/workspace.py` | `Workspace`, `WorkspaceStatus` | `northstar_api.models` / existing `workspaces` table |
| `models/workspace_member.py` | `WorkspaceMembership`, `WorkspaceMemberAgentAccess` | Existing membership and agent-access tables |
| `models/workspace_role.py` | `WorkspaceRole`, `CustomRole`, `RolesSettings` | Original role enum and validated custom-role settings document; **no new role table** |
| `models/workspace_team.py` | `WorkspaceTeam`, `TeamsSettings` | Original validated team settings document; **no new team table** |
| `models/workspace_invitation.py` | `WorkspaceInvitation`, `WorkspaceInvitationAgentAccess`, `WorkspaceInvitationStatus` | Existing teammate-owned invitation ORM tables; no behavioral changes |

`models/__init__.py` preserves the original `WorkspaceConversationAssignment` export and exposes the additional types lazily to avoid importing contracts and invitations prematurely. Existing model and contract imports remain valid. The added identity regression test checks the canonical exports are the *same objects*, the original ORM mappers remain the same, and no extra SQLAlchemy metadata tables appear. It does **not** assert that standalone role/team ORM persistence has been implemented. That requires a separate, tested database migration and must not be inferred from this additive import boundary.

## Shared Workspace settings write serialization

`modules/workspace/repositories/workspace_write_lock.py` provides a single write boundary for the existing Workspace row. After the unchanged scoped membership loader authorizes a caller, mutation endpoints refresh `settings_json`, `branding_json` and `status` using `SELECT ... FOR UPDATE` on PostgreSQL **before** parsing the settings document. The helper refuses workspaces archived between authorization and the lock. The existing endpoint transaction commits or rolls back and releases the lock. No schema changes, new storage paths, route changes or permission changes are introduced.

The settings general/security/notification/developer writers, custom-role/team/dashboard writers, brand draft/publish/rollback writers, and domain create/verify/activate/disable writers now use this boundary. The original `PATCH /workspace` handler also reloads under the same lock, preserving its existing URL, permissions, optional payloads, response and audit/event handling. Member suspension/reactivation and ownership transfer also acquire the lock before checking current state and writing changes. Read-only endpoints do not acquire write locks. New-domain hostname validation runs before the lock, while uniqueness and the 20-domain limit are checked against the reloaded document. Existing DNS/TLS worker and failed-dispatch state locks remain in place.

`test_workspace_settings_write_lock_unit.py` exercises current-row reload, archived-workspace refusal, cross-capability settings preservation and a post-refresh duplicate-domain check. `test_workspace_legacy_write_lock_unit.py` exercises legacy-route settings preservation and archival refusal. `test_workspace_member_status_write_lock_unit.py` covers concurrent member-state preservation and stale ownership transfer. Existing domain creation and TLS route stubs retain their prior behavior with an explicit mocked lock. **These committed tests are not verified passing.** Other Workspace JSON writers and PostgreSQL concurrency must still be audited before claiming global lost-update protection; SQLite does not provide PostgreSQL's row-lock semantics.

## Feature-owned service boundaries

`modules/workspace/services/member_service.py` now owns the last-active-administrator rule and the suspended-member ownership-transfer rule. Existing `members.py` handlers still perform tenant-scoped loading, permission checks, row locking, their established JSON write, audit/event recording, commit and unchanged response contracts. The service checks current roles and the reloaded member status under the caller's lock. `test_workspace_member_service_unit.py` covers single/multiple active administrators, already-suspended members, non-admin changes and transfers.

`modules/workspace/services/settings_service.py` now owns general, security, notification and developer document mutations using the original `settings_document`/`save_document` compatibility pipeline. The security mutation **continues dual-writing the existing `settings_json.security` keys**; unrelated settings remain intact. Their existing routes retain input validation, authorization, row locking, before/after audit metadata, events, commit and response contracts. `test_workspace_settings_service_unit.py` tests persistence, legacy security compatibility, snapshots and cross-section preservation.

`modules/workspace/services/role_service.py` now owns validated custom-role document persistence and a cross-document integrity guard: when a role ID is removed, an existing team must first drop its reference to that ID. The roles route runs its existing permission, membership and agent-scope validation under the shared row lock before invoking the service; a conflicting deletion returns HTTP 409 without saving or auditing a change. Unrelated historical references do not block ordinary role updates because only newly removed IDs are checked. `test_workspace_role_service_unit.py` checks the guard, successful rename, unaffected settings and the original handler transaction boundary.

`modules/workspace/services/team_service.py` owns validated team document persistence without introducing new tables. The teams route retains its existing permissions, tenant-scoped member/agent/role validation, shared row lock, audit/event and commit flow. `test_workspace_team_service_unit.py` checks unrelated settings preservation and validation against the reloaded current roles.

`modules/workspace/services/dashboard_service.py` now owns dashboard settings and branding **draft** layout document updates. It does not alter published branding or published version history. The original dashboard route still acquires its Workspace write lock, calls `persist_branding_document` for normalized dual-write, records audit/outbox, commits, and returns the unchanged response model. `test_workspace_dashboard_service_unit.py` checks draft/published separation, unrelated settings, and dual-write/audit ordering. `test_workspace_service_import_order_unit.py` checks the member/settings/role/team/dashboard services and their legacy handlers in three fresh-interpreter import orders. These are **committed but unverified** tests, not proof of complete section-23 decomposition.

## Import compatibility

The combined `modules.workspace.settings.router`, `modules.workspace.access.router`, and `modules.workspace.branding.router` remain importable. The `modules.branding` package resolves its established public router exports lazily to avoid re-entering the partially initialized legacy branding module. `brand_draft_router` and `brand_versions_router` are additional canonical exports; existing `branding_router`, `domains_router` and `email_router` exports remain available.

## Required verification before closing section 23

These commands are a verification procedure, **not a claim that checks have passed**:

```bash
cd backend
uv sync --all-groups --locked
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy src
uv run pytest tests/test_workspace_module_boundaries.py tests/test_workspace_canonical_api_routes_unit.py tests/test_workspace_settings_split_routes_unit.py tests/test_workspace_branding_split_routes_unit.py tests/test_workspace_branding_import_order_unit.py tests/test_workspace_production_router_registration_unit.py tests/test_workspace_legacy_loader_import_order_unit.py tests/test_workspace_canonical_model_boundaries_unit.py tests/test_workspace_settings_write_lock_unit.py tests/test_workspace_legacy_write_lock_unit.py tests/test_workspace_member_status_write_lock_unit.py tests/test_workspace_member_service_unit.py tests/test_workspace_settings_service_unit.py tests/test_workspace_role_service_unit.py tests/test_workspace_team_service_unit.py tests/test_workspace_dashboard_service_unit.py tests/test_workspace_service_import_order_unit.py tests/test_workspace_domain_creation_constraints_unit.py tests/test_workspace_domain_tls_ownership_unit.py
```

Additionally run the entire backend/frontend quality gates and verify authenticated and unauthorized calls to every migrated route against the previous API contract. Confirm tenant and workspace isolation, no duplicate operation IDs or mapped tables, preserved global entitlement enforcement, and no import-order regressions. Exercise two independent PostgreSQL sessions updating the same Workspace settings row and verify both changes persist without deadlocks, including interleavings with legacy writers and queued domain workers. Section 23 remains **OPEN** until these checks produce successful executable results; section 44 requires further database, security, UI and integration verification before either draft PR can merge into `main`.
