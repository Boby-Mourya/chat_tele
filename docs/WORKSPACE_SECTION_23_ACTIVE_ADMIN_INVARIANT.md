# Workspace section 23 — last-active-administrator invariant

Scope: Workspace member lifecycle only. This change does not alter the teammate's sections 1–22, WhatsApp, Super Admin, invitation flow, route names, permission dependencies, audit/outbox or transaction ownership.

## Why the previous check needed correction

The existing suspension guard queried Workspace administrator membership IDs and excluded members suspended in `workspaceMemberStatusV1`. A disabled `User.is_active = false` still had an administrator membership, so the guard could count that account as an available administrator and permit suspension of the last usable administrator.

## Additive compatibility change

`modules/workspace/services/member_service.py:ensure_member_status_change_allowed` now joins the existing `User` model with `WorkspaceMembership` and includes `User.is_active IS TRUE` alongside the existing tenant ID, workspace ID and admin-role filters. The Workspace settings row is still locked by the existing caller before this query. The existing owner-suspension rule and JSON suspended-state filter both remain in force. An administrator counts only when their user account is enabled and their Workspace membership is not suspended.

No tables, migrations, request schemas, response schemas, HTTP routes or audit events changed. The guard continues to reject attempts to suspend the last available administrator with HTTP 409 and the existing message.

## Regression tests (committed, not verified passing)

`backend/tests/test_workspace_disabled_admin_suspension_unit.py` checks the SQL includes the enabled-account join/filter, refuses a suspension when only the target is enabled, accepts the operation with a second enabled and unsuspended administrator, refuses it if that second administrator is suspended, and confirms rejected changes leave the settings document untouched.

From `backend/`, with project dependencies available:

```bash
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy src
uv run pytest tests/test_workspace_disabled_admin_suspension_unit.py tests/test_workspace_member_service_unit.py tests/test_workspace_owner_lifecycle_unit.py tests/test_workspace_member_status_write_lock_unit.py
```

Before section 23 can be accepted, also test two genuine PostgreSQL sessions and relevant account-disable/member-suspend interleavings and check the broader section-44 acceptance criteria. A committed test or a failing GitHub Actions run is not proof that the feature is complete. Keep #132 and #131 draft and do not merge to `main` until applicable gates pass.
