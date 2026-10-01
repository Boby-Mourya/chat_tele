# Workspace invitations and team membership

This document is the operational contract for the backend-backed Workspace Team feature.

## Scope

The feature replaces browser-only invitation state with persistent, tenant- and workspace-scoped records. It supports:

- inviting a person by email;
- selecting a workspace role;
- granting all-agent access or restricting the person to selected agents;
- SMTP delivery with a retryable delivery state;
- invited account creation;
- acceptance by an existing signed-in account;
- decline, resend, expiry, token rotation, and revocation;
- member role/access updates and removal;
- protection against self-removal and removal/demotion of the last workspace administrator.

API keys, subscriptions, and billing are separate roadmap units and are intentionally not part of this implementation.

## Data model

Migration `0027_workspace_invitations` creates:

### `workspace_invitations`

The record contains the tenant, workspace, normalized invited email, role, all-agent flag, token hash, lifecycle status, inviter/accepter, expiry, consent timestamps, delivery attempts, and delivery error state.

Important constraints:

- one reusable invitation record per workspace and normalized email;
- globally unique token hash;
- foreign keys cascade with the tenant/workspace and use `SET NULL` for deleted inviter/accepter users;
- indexes cover tenant/workspace/status, email, expiry, and user references.

### `workspace_invitation_agent_access`

This table stores the agent allow-list for an invitation when `all_agents_access=false`. The accepted membership receives the same allow-list in `workspace_member_agent_access`.

## Lifecycle

```text
create/reissue
    -> pending
        -> accepted
        -> declined
        -> revoked
        -> expired

expired
    -> resend -> pending with a new token and new expiry
```

A new invitation for an email that already has a declined, revoked, or expired record reuses the record but rotates the token and resets its lifecycle fields. Accepted invitations are no longer exposed in the pending/history administration list.

## Security contract

1. The email link carries the token in the URL fragment (`#token=...`), not the query string.
2. The frontend immediately copies the token into session storage and removes the fragment from the visible browser URL.
3. The backend stores only a SHA-256 token hash.
4. The raw token is never returned by an administration API.
5. Accept, decline, signup, resend, and revoke rotate or invalidate the previous token.
6. Public preview/decline/signup requests are rate-limited by source and token fingerprint.
7. Existing users are never silently added. They must sign in with the exact invited email and explicitly accept.
8. A signed-in user with a different email cannot accept the invitation.
9. Invitation acceptance is not coupled to the user's previously active `X-Workspace-ID` header.
10. Refresh tokens remain HttpOnly cookies in production; the invitation frontend stores only the returned access session.
11. Delivery errors record an exception class, not SMTP credentials or provider response bodies.
12. Agent IDs are validated against the invitation's tenant and workspace before persistence.
13. Team administration requires `members.view` or `members.manage`; management operations require `members.manage`.
14. The service prevents self-removal/self-demotion and preserves at least one workspace administrator.

## Administration API

All administration routes require a bearer token and an active `X-Workspace-ID`.

| Method | Route | Permission | Purpose |
| --- | --- | --- | --- |
| `GET` | `/api/v1/workspace/members` | `members.view` | List active members and their role/agent access |
| `PATCH` | `/api/v1/workspace/members/{user_id}` | `members.manage` | Change role and agent access |
| `DELETE` | `/api/v1/workspace/members/{user_id}` | `members.manage` | Remove a member |
| `GET` | `/api/v1/workspace/invitations` | `members.view` | List non-accepted invitation records |
| `POST` | `/api/v1/workspace/invitations` | `members.manage` | Create or reissue an invitation and deliver it |
| `POST` | `/api/v1/workspace/invitations/{id}/resend` | `members.manage` | Rotate and resend a pending/expired invitation |
| `DELETE` | `/api/v1/workspace/invitations/{id}` | `members.manage` | Revoke an invitation |

The create payload is:

```json
{
  "email": "person@example.com",
  "role": "operator",
  "allAgentsAccess": false,
  "agentIds": ["00000000-0000-0000-0000-000000000000"]
}
```

When `allAgentsAccess=true`, `agentIds` must be empty. Duplicate agent IDs are rejected.

## Invitation API

| Method | Route | Authentication | Purpose |
| --- | --- | --- | --- |
| `POST` | `/api/v1/workspace-invitations/preview` | Public, rate-limited | Validate token and show safe invitation metadata |
| `POST` | `/api/v1/workspace-invitations/decline` | Public, rate-limited | Decline and invalidate token |
| `POST` | `/api/v1/workspace-invitations/signup` | Public, rate-limited | Create an account for a new invited email and accept |
| `POST` | `/api/v1/workspace-invitations/accept` | Bearer token | Accept as an existing matching account |

Tokens are sent in the JSON body:

```json
{
  "token": "raw-one-time-token-from-the-email-fragment"
}
```

## Email delivery

Workspace invitations share the existing account-email SMTP transport.

Required production values:

```dotenv
EMAIL_DELIVERY_MODE=smtp
EMAIL_FROM_ADDRESS=no-reply@example.com
EMAIL_FROM_NAME=Northstar
WORKSPACE_INVITATION_FRONTEND_URL=https://app.example.com/workspace-invitation
WORKSPACE_INVITATION_TTL_DAYS=7
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USERNAME=...
SMTP_PASSWORD=...
SMTP_STARTTLS=true
SMTP_SSL=false
SMTP_TIMEOUT_SECONDS=10
```

`SMTP_STARTTLS` and `SMTP_SSL` cannot both be enabled. `SMTP_HOST` is required when delivery mode is `smtp`.

In development, `EMAIL_DELIVERY_MODE=log` writes the invitation URL to structured logs. Production configuration rejects this raw-link logging path.

A delivery failure does not destroy the invitation. The administration response reports `deliveryState=failed`; an administrator can fix SMTP configuration and resend, which rotates the token.

## Frontend behavior

### Workspace Team panel

The Team section reads members and invitations from the backend. It supports:

- invite modal with role and agent scope;
- active member list;
- pending/history invitation list;
- delivery, expiry, and status display;
- edit member access;
- resend/revoke invitation;
- remove member;
- permission-aware management controls.

No membership or invitation is created in local storage.

### Public invitation page

Route: `/workspace-invitation`

The page:

1. captures and removes the token fragment;
2. previews the invitation;
3. asks a new invitee to create a password and accept legal terms;
4. asks an existing invitee to sign in first;
5. rejects a different signed-in account and offers account switching;
6. activates the accepted tenant/workspace session;
7. clears the pending token after acceptance or decline.

## Deployment

1. Configure the frontend URL and SMTP values.
2. Apply migration `0027_workspace_invitations` with the migration database role.
3. Deploy API and frontend images together.
4. Confirm the public frontend route resolves without authentication.
5. Confirm the API OpenAPI document exposes all routes listed above.
6. Send an invitation to a controlled mailbox.
7. Verify the link opens the correct deployed origin.
8. Complete new-user signup and confirm the active workspace changes.
9. Test an existing user and a deliberately wrong signed-in account.
10. Test restricted agent access from both UI and API.
11. Test resend and confirm the previous token no longer previews.
12. Test revoke/decline and confirm the token no longer previews.

## Verification commands

```bash
# Migration
cd backend
uv run alembic current
# Expected head: 0027_workspace_invitations

# Backend quality gates
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest

# Frontend quality gates
cd ../frontend
npm run lint
npm run typecheck
npm test
npm run build

# Compose syntax (from repository root)
cp .env.example .env
docker compose config --quiet
```

## Rollback

The application should be rolled back before downgrading the database. The migration downgrade drops `workspace_invitation_agent_access` first and then `workspace_invitations`.

Downgrading permanently removes invitation history. Active `workspace_memberships` created by accepted invitations are intentionally independent records and are not deleted by the invitation-table downgrade.
