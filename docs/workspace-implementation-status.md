# Workspace platform implementation status

Branch: `feature/workspace-platform-consolidated-20260917`.
Pull request: #114, draft. This remains an incomplete development checkpoint.

## Current continuation: existing team client reliability

Baseline: `5ce695f6d2298a336f617a2b15bfb8b4cf0d64e8`.
The existing WorkspaceTeamPanel and request module now fence stale account and
workspace responses, cancel superseded reads, guard duplicate submissions, keep
server errors/drafts visible and display saved/failed/unconfirmed invitation email
outcomes truthfully. Explicit capabilities and current self-member agent scope
control UI choices; the backend remains authoritative. Existing member/invitation
endpoints and body shapes are unchanged. There is no dependency on unpublished
backend code, new models, migrations or routes.

Executed for this client checkpoint: 37 actual-source Node module checks with
browser/storage/network fixtures; targeted strict TypeScript 5.8.3; four-file
syntax transpilation. Nine Vitest transport cases and five React/Testing Library
cases were authored but not executed in the full dependency environment. This is
not a React/browser/cookie, backend, full-project lint/format/type/build or
production acceptance result. See [team client operations](operations/team-client-reliability.md).

## Backend governance write blocked; not committed

A separate local backend implementation covered actor/sponsor revalidation,
selected-agent delegation, optional member access versions, last-usable-admin
protection, invitation acceptance conflicts, organization-membership retention,
member-seat checks, transaction-bound audit/outbox, stale SMTP-result fencing and
canonical invitation-route cleanup. The service/schema tree write was blocked by
the repository tool. It was not retried through another route. Its 43 isolated
minimal-host service/router/schema/source checks and nine authored full-host API
regressions are NOT tests or files of this client-only checkpoint.

The existing backend still needs those corrections. Server-side optimistic
version checks, sponsor revalidation, org-membership retention on workspace
removal and removal of the duplicate invitation handler must NOT be claimed as
implemented by these frontend changes. Prepared review code remains separate.

## Retained starter-copy source checkpoint

`5ce695f6d2298a336f617a2b15bfb8b4cf0d64e8` saved approved support-template contracts,
scoped receipt model/migration, transactional clone service, unregistered router,
recovery transport and unmounted confirmation/result UI. Earlier registration
writes were blocked. Starter copying is still NOT enabled in the dashboard or
composed router. Bootstrap/catalog and model metadata registration were not
changed. The receipt migration is source, not a production migration execution.

Historical limited-host checks for that checkpoint: 34 contract/migration, 35
service/router and 36 client-module cases, targeted TypeScript and syntax checks.
Seven Vitest and five React regressions were not executed in the full host.
See [starter copies](operations/starter-template-copies.md).

## Earlier integrated checkpoints retained

- `ba4d4f9`: stable workspace presentation keys, cancelled old reads, same-context
  editor-preserving refresh and explicit errors. Historical 31 Node checks and
  targeted types/syntax, not full React/browser acceptance.
  See [workspace refresh](operations/workspace-refresh.md).
- `c052fe6`: organization chooser and organization-only billing recovery using
  actual membership, matching refresh proof, new-family transfer and audit/outbox
  compensation boundaries. Historical 22 unit, 23 minimal-host ASGI and 26 Node
  checks, not real Redis/PostgreSQL/cookies. See [organization selection](operations/organization-selection.md).
- `d2ad733`: scoped access contracts and truthful billing transport, not full
  custom-role/team runtime. The migration junction joins onboarding and extraction
  without data changes in the junction itself.
- Earlier profile/onboarding/Free/basic-branding and independent PDF-extraction
  code remain preserved. The old PR #113 note is not the current active checkpoint.

## Remaining implementation and release gates

Backend membership governance; full custom roles/teams and resource/field/API/
worker enforcement; starter registration/catalog/playground; versioned whole-app
branding and inheritance; actual auth/widget/email/report surfaces and assets;
verified domains/TLS/senders; lifecycle/archive/export/deletion/retention; usage
reservations/budgets; ownership/security governance; durable signup/invitation
mail; Education/CRM/provider checks; production-like migrations, PostgreSQL locks/
RLS, real Redis/brokers, all frontend/backend CI, accessibility, load and restore.

No blocked backend operation is bypassed by this independent client improvement.
Keep existing quality gates and PR draft state. No main or other branch ref,
production database, deployment, provider or worker configuration is changed.
No merge into main is performed.
