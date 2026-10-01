# Workspace section 23 — ownership and member lifecycle invariant

Scope: Workspace only. This supplements `WORKSPACE_SECTION_23_API_COMPATIBILITY.md` and does not change the teammate-owned invitation, WhatsApp, or Super Admin modules.

## Preserved request pipeline

`POST /workspace/settings/members/{member_user_id}/suspend` and `/reactivate` continue to use the existing member handlers. The handler checks `members.manage`, loads the member through the existing tenant/workspace-scoped loader, takes the shared Workspace row write lock, reloads the target membership, applies the feature-owned member-service policy, modifies the existing `workspaceMemberStatusV1` JSON, records the existing audit/outbox event, and commits. No new database models, migrations, routes, permissions, or storage format were introduced.

The original `transfer-ownership` handler still requires a Workspace administrator and still changes the target membership to `workspace_admin` and `workspace.created_by` in its existing transaction. It refuses suspended recipients **and disabled user accounts**. The active-account check uses the `User.is_active` value retrieved with the target's tenant/workspace-scoped membership. The original two-argument member-service helper remains callable; the handler explicitly passes `account_is_active=user.is_active`. A rejected transfer returns HTTP 409 before changing membership, owner, audit/outbox or committing.

## Additional safety rules

The member service returns HTTP 409 if someone attempts to suspend the current owner (`workspace.created_by`), even if another active administrator remains. Transfer ownership to an active member first; suspending the former owner after that transfer remains possible, subject to the existing last-active-admin rule. Reactivating a suspended owner is not blocked.

A disabled user account cannot receive ownership merely because its Workspace membership has not been suspended. Reactivate the user account before attempting a transfer. This is distinct from the existing Workspace suspension check; both must pass. This change does not itself implement organization-wide account reactivation.

The shared `lock_workspace_settings` call refreshes `created_by` alongside `settings_json`, `branding_json`, and `status` under the existing PostgreSQL `SELECT ... FOR UPDATE`. This prevents a stale owner snapshot from being used after a concurrent ownership transfer. The original update routes also use this shared lock; updating its refresh attribute list does not change endpoint contracts. The account-status check reads the target user after the Workspace lock; cross-transaction user deactivation still needs an integration interleaving test before claiming full cross-table serialization.

## Regression coverage added or updated (not yet verified passing)

- `tests/test_workspace_owner_lifecycle_unit.py`: current owner (administrator or manager) cannot be suspended; a different administrator remains suspendable when another active admin exists; owner reactivation is permitted.
- `tests/test_workspace_disabled_owner_policy_unit.py`: disabled account is rejected; Workspace-suspended account is still rejected; existing two-argument service callers remain compatible.
- `tests/test_workspace_member_status_write_lock_unit.py`: ownership transferred after the scoped read but before the lock prevents suspension; a disabled account cannot receive ownership; rejected operations do not mutate owner/membership or commit; prior membership/JSON preservation tests remain.
- `tests/test_workspace_settings_write_lock_unit.py`: verifies the owner field is refreshed with settings and status and archival remains blocked.
- `tests/test_workspace_legacy_write_lock_unit.py`: preserves the original `/workspace` write-lock expectation with the additional owner field.

Run from `backend/` after dependencies are available:

```bash
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy src
uv run pytest tests/test_workspace_owner_lifecycle_unit.py tests/test_workspace_disabled_owner_policy_unit.py tests/test_workspace_member_service_unit.py tests/test_workspace_member_status_write_lock_unit.py tests/test_workspace_settings_write_lock_unit.py tests/test_workspace_legacy_write_lock_unit.py
```

Also exercise independent PostgreSQL sessions with an ownership transfer committing while suspension waits for the Workspace row lock, then verify suspension returns 409 and the new owner stays active. Verify a concurrent account-deactivation/ownership-transfer interleaving as well. All section-23 and section-44 acceptance checks remain open until there are executable passing results. Do not merge either Workspace draft PR into `main` on the strength of committed tests alone.
