# Section 23 — Workspace Teams business-hours timezone validation

Scope: Workspace only; teammate sections 1–22, WhatsApp 24–26 and Super Admin 31 remain untouched. This is a focused addition on corrective draft PR #132, targeting the existing Workspace branch in draft PR #131.

## Current pipeline retained

The existing `PATCH /workspace/settings/teams` handler still performs its permission dependency and tenant/workspace-scoped load, takes the shared Workspace row lock, validates member/manager/agent/role references, persists teams via `services/team_service.py`, records the established audit/outbox event, and commits. Its URL, input/output schema, settings JSON representation, status codes for existing conditions and transaction ownership remain unchanged. Existing persisted teams are not rewritten by this change.

## Added integrity rule

`BusinessHours.timezone` is a string in the original team contract. Previously, General settings invoked `validate_business_timezone` but Teams did not, allowing a newly submitted team to persist an unrecognized IANA timezone. The team API validator now calls the **existing** `security_policy.validate_business_timezone` for every requested team before membership and agent queries. The feature-owned team persistence service calls the same validator before reading or modifying the shared Workspace settings document so internal service callers cannot bypass this check. An unknown timezone returns HTTP 422; a valid timezone continues through the original update/audit/commit pipeline.

The rules are applied to *incoming team updates*, not a mass rewrite or migration of previously persisted data. No new module, table, dependency, schedule engine, or background task is introduced.

## Committed regression tests — results unverified

- `backend/tests/test_workspace_team_business_hours_timezone_unit.py`: rejects an invalid timezone before membership reads; checks every team in the request; rejects invalid updates after the lock without saving, auditing or committing; accepts `Asia/Kolkata` while preserving unrelated Workspace data and the original lock → query → audit → commit behavior.
- `backend/tests/test_workspace_team_timezone_service_unit.py`: direct service calls reject an invalid timezone before mutation; valid timezones persist without erasing General or unrelated settings.
- Existing `backend/tests/test_workspace_team_service_unit.py` continues to cover scoped-role validation and settings isolation.

From `backend/` with the project dependencies available:

```bash
uv sync --all-groups --locked
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy src
uv run pytest tests/test_workspace_team_business_hours_timezone_unit.py tests/test_workspace_team_timezone_service_unit.py tests/test_workspace_team_service_unit.py
```

Then run the complete backend/frontend, PostgreSQL concurrency and migration verification procedures referenced in `WORKSPACE_SECTION_23_API_COMPATIBILITY.md`. Tests committed to GitHub are **not evidence of passing execution**. Keep both PRs drafts; section 23 remains open and do not merge into `main` until all relevant section-44 acceptance conditions are verified.
