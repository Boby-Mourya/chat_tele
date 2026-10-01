# Starter-template copy source: not yet enabled

Branch: `feature/workspace-platform-consolidated-20260917`.
Baseline: `ba4d4f9a4b1b78b7d456b4115617f9ca4b04b062`.

## Delivery boundary

The branch contains standalone clone contracts, receipt model/migration, service, router, client transport, confirmation/result component and tests. **It does not expose the clone endpoints or the dashboard button.** The repository tool blocked the batch updating API router registration, catalog/bootstrap output and Alembic model registration. That batch was not retried through an alternate route. Its edits, the dashboard mount and normal backend endpoint tests remain in the separate local review bundle.

Existing application routes, dashboard, providers and model configuration remain unchanged. Do not register or activate this feature until the integration edits and full application acceptance can be completed. PR #114 remains draft.

## Source behavior tested in isolated hosts

Only the existing approved `support-template` recipe can be copied. Tutorials remain read-only. The clone payload accepts only a UUID `idempotencyKey`, strict positive integer `catalogVersion`, and visible 2–120 character name. Caller-provided tenant/workspace, roles, instructions, model, purpose or activation state are rejected.

The service creates a Support/Website draft using existing model and security defaults. It does not copy private knowledge, credentials, students, conversations, leads, integrations or memberships. It performs no inference, ingestion, deployment or external-provider call. The source catalog is immutable from this operation. Explicit source/version/digest lineage is recorded.

Current interactive workspace membership, user status, profile, effective permissions and catalog grants are rechecked. Required permissions are `starter_content.read`, `agents.create` and `agents.view`. New copies call the existing channel/capacity services and tenant/agent advisory lock. A selected-agent creator gets an explicit grant for the new draft only.

Agent, purpose, website binding, optional selected-agent grant, receipt, audit and outbox effects commit together. A repeated exact request returns the original copy without a new slot or creation event. Changed payloads conflict. Revoked grants are not restored. A deleted copy returns 410 rather than being resurrected. A receipt lookup is scoped to its actor, tenant and workspace.

The unregistered router defines `POST /starter-content/{catalog_id}/clone` (201 create / 200 replay) and `GET /starter-content/clone-requests/{request_id}` (read-only recovery). These are source contracts, not currently reachable application endpoints. `initialStatus: draft` describes creation rather than any later user edits.

The client saves a tab-scoped request ID before submitting, persists no credentials in that receipt, keeps the same ID after interruption/name edits, and rejects old-context responses. It never automatically repeats a POST. Check result uses GET. A new copy requires an explicit reset after a validated result. Destroying browser storage cannot guarantee recovery; inspect existing agents before intentionally creating another copy in a new tab/device.

## Migration and pipeline

`0045_starter_template_clones` descends from `0044_merge_workspace_extraction`. The migration creates only the receipt table/index and PostgreSQL policy/grants. It is committed as source and has not been executed against a production database. It can create an unused receipt table while the router is not registered. The model's Alembic metadata registration remains unpushed.

PostgreSQL RLS checks tenant context and validates linked workspace/agent scope on insert. The service adds actor/workspace filters. This does not establish full sibling-workspace RLS for other tables. Actual runtime roles, lock order and concurrent execution still need PostgreSQL acceptance.

The service uses the existing transactional outbox for `agent.created.v1` and `starter_content.cloned.v1`. Provision the latter topic and publisher permissions where auto-creation is disabled before activation. No new worker topology or direct best-effort broker publish is introduced.

Downgrade preserves customer agents but removes receipt history. Once activated, disable clone writes before rollback and do not replay old requests after receipt loss. Receipt deletion is not idempotency-safe rollback.

## Verification boundaries

Executed: 34 isolated contract/SQLite migration tests; 35 actual new-router/service checks in a minimal synchronous SQLAlchemy/SQLite host with recording quota/channel/audit/outbox adapters; 36 Node checks of actual client/workspace/storage modules with explicit fixtures; strict TypeScript 5.8.3 transport checking with a minimal Vite declaration; syntax transpilation and Python compilation.

Seven normal Vitest and five React/Testing Library regressions are committed but were not executed here. Normal backend endpoint integration tests remain local because the router is unregistered. The Node runner is `node --test scripts/check_starter_clone_transport.cjs` after dependencies are installed.

These counts are not full application, real authentication/cookies, async database driver, PostgreSQL/RLS/concurrency, React/browser rendering, broker/provider or production acceptance. Complete all existing CI gates and the saved integration before enabling this feature. The complete catalog/playground, access/branding/lifecycle/budget specification and merge readiness remain outstanding.
