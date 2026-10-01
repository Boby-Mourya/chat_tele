# Workspace Architecture — Items 23–44

This document describes the workspace-owned implementation on the `workspace-23-44` branch. It continues from `workspace-1-22` and deliberately follows a compatibility-first migration. Existing workspace, branding, billing, integrations, authentication, conversations, and legacy routes remain available while feature-owned boundaries become canonical.

## Scope

Implemented in this branch:

- 23 — backend workspace/branding feature module boundaries
- 24–26 — canonical WhatsApp module boundaries and durable message/status/template pipelines
- 27–28 — configurable workspace dashboard architecture and feature-owned frontend structure
- 29–30 — tenant/workspace-scoped normalized branding persistence with compatibility dual-write
- 32 — grouped workspace Settings information architecture
- 33–34 — naming and scoped file-size architecture guardrails
- 35–36 — feature-owned CSS and centralized white-label design tokens
- 37–38 — normalized brand/domain resolution, versioned cache and cache invalidation
- 39 — workspace administrative audit enrichment
- 40 — typed workspace domain events through the existing outbox
- 41 — asynchronous branding/domain operations using the existing Celery/RabbitMQ worker system
- 42–44 — staged migration rules, completion documentation and regression coverage
- 31 — isolated platform-admin control plane, entitlement/configuration visibility, audited lifecycle controls and time-boxed support sessions

Repository-wide CRM/Education/Agents/Leads/Conversations reorganizations beyond the workspace
boundaries remain outside this plan. Their existing compatibility adapters continue to be used.

The former teammate-owned WhatsApp and platform-admin boundaries are now included as additive
extensions: legacy imports/routes remain available, while new code uses the canonical namespaces
and the platform control plane is isolated from workspace context requirements.

## 23. Backend module structure

Canonical feature boundaries now exist at:

- `backend/src/northstar_api/modules/workspace/api/`
- `backend/src/northstar_api/modules/workspace/services/`
- `backend/src/northstar_api/modules/workspace/models/`
- `backend/src/northstar_api/modules/workspace/schemas/`
- `backend/src/northstar_api/modules/workspace/permissions/`
- `backend/src/northstar_api/modules/workspace/repositories/`
- `backend/src/northstar_api/modules/workspace/events/`
- `backend/src/northstar_api/modules/branding/api/`
- `backend/src/northstar_api/modules/branding/services/`
- `backend/src/northstar_api/modules/branding/models/`
- `backend/src/northstar_api/modules/branding/schemas/`
- `backend/src/northstar_api/modules/branding/repositories/`
- `backend/src/northstar_api/modules/branding/workers/`

The original flat implementation modules remain compatibility adapters during the staged migration. The application router imports through the canonical feature boundary.

## 27–28. Dashboard architecture

The configurable dashboard now has distinct responsibilities:

- `DashboardPage.tsx` — workspace/role/profile composition
- `DashboardGrid.tsx` — 24-column published layout
- `dashboard.api.ts` — safe workspace runtime context
- `dashboard.types.ts` — viewer/layout contracts and visibility rules
- `widgets/` — individual dashboard widgets
- `editor/DashboardEditor.tsx`
- `editor/WidgetLibrary.tsx`
- `editor/WidgetSettings.tsx`
- `editor/LayoutPreview.tsx`

Widget visibility can use:

- workspace
- workspace role
- explicit permissions
- workspace industry/profile
- enabled plan features
- published visibility/audience configuration
- pinned ordering
- saved coordinates and dimensions

The existing Overview dashboard remains the compatibility fallback when no published configured dashboard applies.

## 29–30. Database and white-label persistence

Migration `0058_workspace_branding_tables.py` adds normalized workspace-owned records:

- `workspace_brand`
- `workspace_brand_asset`
- `workspace_brand_theme`
- `workspace_brand_surface`
- `workspace_brand_version`
- `workspace_custom_domain`
- `workspace_dashboard_layout`
- `workspace_email_brand`
- `workspace_widget_brand`

Every normalized workspace-owned record carries `tenant_id` and `workspace_id` (or has `workspace_id` as its primary key plus a required `tenant_id`).

The branch uses compatibility dual-write: `settings_json.workspaceSettingsV2` remains readable/writable while normalized records are populated. This prevents a destructive big-bang data migration and allows rollback during deployment.

## 32. Settings UI

The settings navigation is grouped by business capability:

### Workspace
- General
- Members
- Teams
- Roles & permissions

### Customization
- White label
- Dashboard
- Widget
- Email

### Communication
- Channels
- Notifications
- Business hours

### Integrations
- CRM
- Apps
- Webhooks

### Security
- Authentication & security
- MFA
- Sessions
- Audit

### Developer
- API keys
- OAuth apps
- Webhooks
- API logs

### Account
- Billing
- Usage

New subsection routes reuse the existing feature owners instead of creating duplicate backend services.

## 33–34. Naming and file-size rules

`scripts/validate-architecture.sh` now checks the new workspace/branding/dashboard boundaries. New code in these feature areas must use capability-owned filenames rather than generic names such as `helpers`, `common`, `utils2`, or `final_service`.

Scoped line-count signals are enforced for the new feature boundaries so newly migrated files do not grow into multi-responsibility pages/services. Historic legacy code is not made to fail solely because it predates this rule.

## 35–36. CSS and design tokens

New dashboard styling is feature-owned instead of appended to the global stylesheet.

Shared theme files include:

- `theme/tokens.css`
- `theme/typography.css`
- `theme/brand-tokens.ts`

The central resolver controls:

- `--brand-primary`
- `--brand-primary-hover`
- `--brand-secondary`
- `--brand-accent`
- `--brand-background`
- `--brand-surface`
- `--brand-border`
- `--brand-text`
- `--brand-muted`
- `--brand-sidebar`
- `--brand-sidebar-text`
- `--brand-header`
- `--brand-success`
- `--brand-warning`
- `--brand-error`
- `--brand-link`
- `--brand-radius`
- `--brand-font`
- `--brand-heading-font`
- `--brand-font-size`

Token application is layered. Removing a workspace-specific layer restores the previous public/platform layer rather than clearing unrelated theme state.

## 37. Brand resolution

Runtime resolution is:

1. normalize hostname
2. resolve an `active` custom domain
3. resolve tenant/workspace identity
4. read the published workspace brand/version
5. prefer normalized branding storage
6. fall back to compatibility JSON during migration
7. cache the published result
8. bootstrap safe public tokens before authentication

Migration `0059_workspace_brand_domain_resolver_normalized.py` upgrades the pre-auth PostgreSQL `SECURITY DEFINER` resolver to prefer normalized `workspace_custom_domain` records and retain the legacy JSON fallback.

This workspace-only phase does not invent a separate organization-wide brand model where the repository does not currently have one. Platform defaults remain the final fallback; a future tenant-brand feature can be inserted between workspace and platform without changing the public contract.

## 38. Caching

Redis keys include:

- `northstar:brand:domain:{hostname}`
- `northstar:brand:workspace:{workspace_id}`
- `northstar:brand:version:{workspace_id}:{version}`

Version keys are immutable snapshots with a longer TTL. Workspace/domain keys are mutable aliases.

Publication sequence:

1. validate entitlement
2. create version
3. persist compatibility JSON and normalized records in the transaction
4. commit
5. populate immutable version cache
6. invalidate mutable workspace/domain aliases
7. publish `northstar:brand-updated`

Redis errors fail open to durable database resolution rather than making branding a hard dependency on cache availability.

## 39. Audit requirements

Workspace administrative writes use the existing durable audit model and now support:

- actor
- tenant
- workspace
- action
- resource type/id
- before value
- after value
- changed fields
- reason
- IP
- user agent
- request ID
- timestamp (audit model timestamp)

The existing recursive redaction layer remains in force for tokens, passwords, secrets, API keys, cookies, authorization values and related sensitive keys.

Core settings, role/team/dashboard, branding publication/draft/rollback and domain operations pass request and before/after metadata through the workspace event boundary.

## 40. Event architecture

`modules/workspace/events/administrative_events.py` is the workspace administrative event boundary. It writes the audit projection and enqueues an outbox event in the same transaction.

Stable event names include:

- `WorkspaceUpdated`
- `WorkspaceSecurityUpdated`
- `WorkspaceNotificationsUpdated`
- `WorkspaceDeveloperSettingsUpdated`
- `WorkspaceMemberInvited`
- `WorkspaceMemberRoleChanged`
- `WorkspaceMemberSuspended`
- `WorkspaceMemberReactivated`
- `WorkspaceRoleUpdated`
- `WorkspaceTeamsUpdated`
- `BrandUpdated`
- `BrandPublished`
- `BrandRolledBack`
- `CustomDomainCreated`
- `CustomDomainVerified`
- `CustomDomainActivated`
- `CustomDomainDisabled`

Unknown future workspace actions remain forward compatible through `WorkspaceAdministrativeChanged`.

The durable outbox is used rather than coupling HTTP controllers directly to email/webhook/analytics consumers.

## 41. Queue responsibilities

The repository already uses Celery + RabbitMQ. This branch reuses that system rather than introducing BullMQ/RQ.

Custom-domain DNS verification and TLS readiness are now asynchronous:

HTTP request
→ validate permission/state
→ persist `verifying` or `certificate_pending`
→ audit + outbox
→ commit
→ enqueue Celery task on `operations`
→ worker performs DNS/TLS I/O
→ worker updates durable domain state
→ normalized dual-write
→ worker audit + outbox
→ cache invalidation

Tasks:

- `northstar.verify_workspace_brand_domain`
- `northstar.check_workspace_brand_tls`

Both use retry/backoff and run through the existing durable worker infrastructure.

## 42. Implementation phases used

This branch follows the requested sequence instead of a folder rewrite:

1. establish canonical feature boundaries
2. keep compatibility imports/routes
3. split dashboard responsibilities
4. add normalized persistence without removing JSON
5. wire dual-write
6. reorganize settings navigation
7. enforce new naming/size rules only on migrated code
8. centralize design tokens
9. move resolution/cache to normalized-aware services
10. enrich audit/events
11. move slow network operations to workers
12. add characterization/regression tests
13. validate before merging

## 43. Migration principle

For each migrated capability:

existing behavior
→ characterization coverage
→ canonical module/component
→ update production import/use
→ retain compatibility adapter
→ validate
→ remove old path only in a later migration after downstream consumers are confirmed

This branch intentionally does **not** delete the old workspace/settings/branding JSON path or legacy frontend routes. Removal is a later migration, not a prerequisite for feature ownership.

## 44. Definition of complete — workspace scope

### Workspace/settings

- persisted — implemented
- tenant/workspace scoped — implemented
- backend permission protected — implemented
- frontend permission protected — implemented in the parent workspace settings phase
- validated — implemented
- audited — implemented/enriched
- tested — focused backend/frontend tests added; full CI remains the release gate
- API documented — items 1–22 and 23–44 documents
- loading/error/empty states — implemented in workspace settings/dashboard surfaces
- destructive actions confirmed — retained from workspace settings/branding controls

### White label

- dashboard — implemented
- authentication — implemented
- widget — implemented
- email — implemented
- custom domain — implemented with async verification/TLS lifecycle
- assets — implemented and normalized
- design tokens — centralized
- preview — implemented
- draft — implemented
- publish — implemented
- versions — implemented
- rollback — implemented
- cache invalidation — implemented post-commit
- entitlement enforcement — backend enforced

### Platform administration and WhatsApp extensions

- platform-admin routes are guarded by the platform-admin allowlist, reject API keys, and do not
  inherit a workspace header or workspace setup gate
- tenant subscription/lifecycle changes and support sessions require a reason and durable audit
  metadata; support tokens are short-lived, tagged, and revocable
- the canonical WhatsApp namespace owns Graph/accounts/messages/status/templates boundaries while
  legacy service imports remain compatibility adapters
- inbound/outbound WhatsApp work remains on the dedicated durable worker path, separate from
  document ingestion and protected by workspace/connection scoping

## Validation checklist before merge

Run or require:

- repository architecture validation
- backend Ruff/format/type checks configured by CI
- backend workspace/branding unit and API tests
- migration head/upgrade validation
- frontend ESLint
- frontend TypeScript typecheck
- frontend Vitest suite
- frontend production build
- security/deployment CI gates

If CI infrastructure fails before executing steps, that condition must be reported as infrastructure failure rather than treated as either a pass or a code-test failure. The branch should not be merged under a false green status.
