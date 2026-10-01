# Workspace Settings & Branding — Items 1–22

This document describes the workspace-owned implementation on the `workspace-1-22` branch. The implementation follows the existing application pipelines, keeps legacy workspace routes available, and intentionally excludes platform-admin/super-admin work and the item-23+ reorganization owned by the next phase.

## Scope and compatibility

- Existing `/workspace` and `/workspace/white-label` routes remain available.
- The settings center is additive under `/workspace/settings/:section`.
- Existing invitations, workspace membership, API keys, MFA, billing, audit, channels, CRM/integrations, notifications, widget, email and authentication services are reused rather than replaced.
- Platform-admin code is not modified by this branch.
- New workspace configuration is stored under the existing workspace-scoped `settings_json.workspaceSettingsV2` document. Published identity compatibility remains in `branding_json`.
- No existing feature file is intentionally deleted.
- New database migrations are additive.

## Frontend settings routes

| Route | Purpose |
| --- | --- |
| `/workspace/settings/general` | Workspace identity, locale and business hours |
| `/workspace/settings/members` | Members, invitations and member lifecycle |
| `/workspace/settings/roles` | Custom roles, capabilities and enforced resource scopes |
| `/workspace/settings/teams` | Workspace team configuration |
| `/workspace/settings/security` | Enforced workspace security controls |
| `/workspace/settings/notifications` | Workspace notification controls |
| `/workspace/settings/channels` | Entry into the existing channel pipeline |
| `/workspace/settings/integrations` | Entry into the existing integrations pipeline |
| `/workspace/settings/developer` | Scoped API keys and developer policy |
| `/workspace/settings/audit` | Entry into the existing audit pipeline |
| `/workspace/settings/billing` | Existing billing/usage surface |
| `/workspace/settings/branding` | White-label control center |

Navigation and direct rendering are permission-aware. Branding view, edit, publish and domain-management capabilities are independent; actions are separately gated in the UI and API.

## Backend workspace boundary

Workspace-owned additions live under `backend/src/northstar_api/modules/workspace/`:

- `settings.py` — permission-filtered settings read plus general/security/notifications/developer writes
- `general.py` — workspace/organization/status/owner metadata
- `members.py` and `member_state.py` — workspace member lifecycle layered over existing membership/invitation services
- `access.py` — custom roles, teams and dashboard validation/persistence
- `security_policy.py` — authentication/request/invitation security enforcement helpers
- `api_key_scopes.py` — service-key scope mapping
- `branding.py` — brand draft, runtime, publish, version and rollback behavior
- `domains.py` — custom-domain DNS ownership and HTTPS/TLS activation lifecycle
- `brand_cache.py` — published-brand cache and invalidation
- `domain_resolution.py` — active custom-domain resolution before authentication
- `email_branding.py` and `email_routes.py` — branded template rendering, preview/test and delivery integration
- `conversation_assignment_model.py`, `conversation_assignments.py` and `conversation_scope.py` — conversation assignment and request-scoped resource enforcement
- `contracts.py` — validated workspace-owned contracts
- `store.py` — compatibility storage plus existing audit/outbox integration

The module is registered alongside the legacy workspace routers, not as a destructive replacement.

## Core API surface

Authenticated routes use the existing bearer authentication and active workspace context.

### Settings and access

- `GET /workspace/settings` — compatibility bundle filtered server-side by the caller's capabilities
- `GET /workspace/settings/capabilities` — role-management capability catalog; requires `roles.manage`
- `GET /workspace/settings/general/metadata`
- `PATCH /workspace/settings/general`
- `PATCH /workspace/settings/security`
- `PATCH /workspace/settings/notifications`
- `PATCH /workspace/settings/developer`
- `PATCH /workspace/settings/roles`
- `PATCH /workspace/settings/teams`
- `PATCH /workspace/settings/dashboard`

`GET /workspace/settings` does not expose every persisted section to every settings user. Security/developer values, role/team values and branding values are populated only when the principal has the corresponding capability.

### Conversation assignment

- `GET /workspace/settings/conversation-assignments/options`
- `GET /workspace/settings/conversation-assignments/{conversation_id}`
- `PUT /workspace/settings/conversation-assignments/{conversation_id}`
- `DELETE /workspace/settings/conversation-assignments/{conversation_id}`

Assignment writes require `conversations.assign`. User/team references are validated inside the same tenant/workspace. Suspended members are excluded from assignment options.

Custom-role conversation scope is enforced as follows:

- `all` — no assignment-level narrowing beyond the existing workspace and agent scope.
- `team` — a conversation must be assigned to one of the caller's configured workspace teams and remain inside that team's configured agent boundary.
- `assigned` — conversation ORM reads for that request-scoped SQLAlchemy session are limited to conversations assigned to the current user.

When multiple custom roles are assigned, broader `all`/`team` scope prevents an `assigned` role from unexpectedly narrowing a broader grant.

### Branding

- `GET /workspace/settings/branding` — branding-only response; unrelated security/developer/role policy is not returned
- `GET /workspace/settings/runtime-branding`
- `PATCH /workspace/settings/branding/draft`
- `POST /workspace/settings/branding/publish`
- `POST /workspace/settings/branding/rollback`
- `POST /workspace/settings/branding/email/preview`
- `POST /workspace/settings/branding/email/test`
- `POST /workspace/settings/domains`
- `POST /workspace/settings/domains/{domain_id}/verification-start`
- `POST /workspace/settings/domains/{domain_id}/activation-check`
- `POST /workspace/settings/domains/{domain_id}/disable`

Public pre-auth brand discovery is separate at `GET /branding/public?hostname=...`; it returns safe published public-brand fields and does not require authentication.

## General settings

General settings extend the existing workspace update/preferences pipeline rather than replacing it. The UI includes workspace name, ID, slug, organization, industry, country, timezone, default language, date/time format, currency, week start, business hours, status, owner, icon and description.

Business hours use validated IANA timezones and server-validated daily time ranges.

## Members and invitations

The implementation reuses the existing invitation and membership pipelines for:

- invite
- resend/revoke invitation
- change built-in workspace role
- all-agent or selected-agent access
- remove member
- suspend/reactivate member
- MFA and last-active visibility
- workspace team count
- ownership transfer

Team membership is configured in the Teams section so there is one workspace team source of truth. Administrative lifecycle changes are workspace scoped and audited.

## Roles and resource access

Canonical built-in workspace roles remain in the existing access policy. Custom roles are additive and can contain only registered workspace permissions; the backend rejects privilege delegation beyond the acting administrator's own grants.

Implemented custom-role resource enforcement includes:

- selected-agent restriction, intersected with the member's existing agent access
- assigned conversations
- team conversations
- all conversations

Custom roles can be assigned to workspace members without replacing their existing built-in workspace role. Unknown permissions, invalid/out-of-workspace member or agent references, duplicate role IDs and unknown role references are rejected server-side.

## Teams

Workspace teams support members, managers, custom-role references, queue IDs, agent ownership, channel IDs, business hours/timezone and routing/escalation description.

Server validation enforces unique team IDs/names, workspace-local members/agents, manager membership and known role references. Team-conversation visibility uses the persisted conversation team assignment plus the configured team-agent boundary.

## Security

Only controls with a real backend behavior are exposed. Current workspace enforcement includes:

- MFA policy (`optional`, workspace administrators, or all members)
- session timeout using access-token issue time
- IPv4/IPv6 allow/deny CIDR policy using the request peer address
- trusted invitation email domains
- suspended-member blocking
- password minimum length when an invitation creates a new account for this workspace
- sensitive-data masking compatibility configuration
- webhook signing/security policy configuration
- security notification configuration

Existing account passwords remain account-level credentials, so the workspace UI does not claim that a workspace-specific minimum retroactively controls account-wide password reset. Existing MFA services are reused. SSO/SCIM switches are intentionally not fabricated because this repository does not currently contain a workspace IdP/SCIM provisioning model.

## Notifications

Workspace notification settings are persisted and consumed by the existing notification service. Member/security/billing/channel/integration categories can be enabled or disabled, and explicit recipients can replace the default workspace admin/manager recipient set.

## Developer settings and API keys

The existing Workspace API Key pipeline is retained and extended with explicit service scopes. Effective API-key permissions are the intersection of the service workspace role and the stored key scopes, so a key cannot become unrestricted through the frontend.

Developer policy stores sandbox mode, webhook signing, event subscriptions, rate limit, request-log retention and webhook retry count. Existing integration/webhook services remain the system of record for actual connection management rather than being duplicated under Settings.

## White label

### Draft, preview, publish and rollback

Brand edits update draft state only. Publishing:

1. checks the workspace plan entitlements;
2. creates a new immutable brand version;
3. promotes the draft to published state;
4. updates the legacy published identity compatibility payload;
5. commits the workspace transaction;
6. invalidates workspace/domain/version brand caches;
7. records the administrative audit/outbox event.

Rollback copies a historical version into a new draft and publishes it as a new version; historical versions are never edited in place.

### Brand surfaces

The control center supports identity assets, extended design-token colors, typography, dashboard appearance/navigation, configurable dashboard widgets, public authentication, email templates, website widget branding, custom domains and version history. Arbitrary customer CSS is not accepted.

### Configurable dashboard runtime

Published widget layout is configuration data (`x`, `y`, `width`, `height`, visibility, audience and widget config). The runtime covers the editor's selectable widget types, including welcome content, KPI cards, conversation and lead summaries/trends, channel health, agent activity, CRM, education, quick actions, announcements and usage. The legacy dashboard remains the fallback when branded dashboard publication is disabled or no configured widgets are published.

### Public authentication branding

Brand lookup occurs before authentication by hostname. Only an active server-verified custom domain can resolve workspace public branding. Safe published design/authentication fields are used by login, signup, forgot-password, reset-password and MFA surfaces. Platform-host behavior remains the fallback.

### Custom-domain lifecycle

1. an authorized workspace administrator creates a hostname record;
2. the server issues a TXT verification name/value;
3. DNS ownership is verified server-side;
4. successful proof moves the domain to `verified`;
5. activation rejects private/internal address resolution and requires a successful valid-TLS HTTPS request to the branding health endpoint;
6. only a successful HTTPS check moves the domain to `active`;
7. an authorized administrator can disable the domain.

The frontend cannot mark a domain verified or active directly.

### Branded email

Published branded email templates cover invitation, password reset, email verification, security, billing, conversation, lead and education categories. Template variables are escaped during HTML rendering. Test delivery uses the existing configured mail transport; production log-only mode is rejected instead of pretending delivery occurred.

Workspace invitations use the workspace's published email brand. Password-reset/email-verification requests use workspace branding only when the incoming hostname resolves to an active workspace custom domain, avoiding arbitrary workspace selection for users who belong to multiple workspaces.

### Chat widget

Published workspace widget configuration is layered over the existing per-agent widget appearance. Supported workspace overrides include launcher icon/color/position, greeting, widget logo, header, background/message colors, avatars, font, privacy link, powered-by label, business hours and offline message. Unconfigured workspaces retain the existing widget behavior.

## Caching, events and audit

Published brands are cached by workspace/domain/version. Publish, rollback and domain lifecycle changes invalidate affected entries after persistence. Administrative writes reuse the repository's existing audit and outbox/event paths; secrets are not introduced into the settings audit payloads.

## Database migrations

- `0055_workspace_brand_domain_resolver.py` — pre-auth active-domain workspace resolver
- `0056_workspace_api_key_scopes.py` — persisted Workspace API Key scopes with compatibility defaults
- `0057_workspace_conversation_assignments.py` — additive tenant/workspace keyed conversation-assignment table

These migrations extend current behavior without removing existing workspace data.

## Tests and release qualification

Focused regression coverage includes settings API behavior, general/security contracts, permission-filtered settings reads, custom-role/team/conversation semantics, notification policy behavior, branded email/domain behavior and public-brand bootstrap behavior.

The repository's GitHub Actions workflow remains the authoritative full frontend lint/type/test/build, backend Ruff/format/Mypy/Pytest, configuration, security and integration gate. A workflow run that fails before executing any steps is treated as runner/infrastructure failure rather than a code-test pass or a code-test failure.

## Explicit exclusions

This branch does **not** implement:

- platform-admin/super-admin control-plane work, even where the source specification discusses it;
- the detailed backend module layout beginning at item 23;
- the WhatsApp domain reorganization following item 23;
- unrelated CRM/Education/Agent/Lead feature restructuring.

Those remain separate teammate/next-phase ownership areas. This branch is intentionally limited to workspace-owned items 1–22 and the runtime changes necessary to make those workspace settings real rather than cosmetic.
