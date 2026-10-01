# Workspace team client reliability

Branch: `feature/workspace-platform-consolidated-20260917`; baseline:
`5ce695f6d2298a336f617a2b15bfb8b4cf0d64e8`. PR #114 remains draft.

This checkpoint changes the existing WorkspaceTeamPanel and its existing request
module. It requires no new backend endpoint, schema, database model or migration.
All original invitation/member endpoint paths and body shapes are retained.

## Behavior

The team client captures the current presentation identity and selected workspace
before a request. It checks them after the response and after JSON parsing; an
old account/workspace response is not applied to the new team's state. GETs may
complete after ordinary same-identity token renewal, but a potentially completed
mutation whose bearer changed is reported as uncertain. The module never
refreshes a session or automatically replays POST, PATCH or DELETE requests.
Read cancellation is passed through to fetch; request caching is disabled.

The editor has a separate mounted instance for each account/workspace/effective
permission snapshot. Superseded list requests are cancelled and generation checks
ignore late results. A synchronous busy guard rejects duplicate submissions.
Errors leave the draft available for review and offer explicit reload rather than
reporting a successful save. Existing member update/delete requests do NOT gain
server-side optimistic concurrency in this client-only checkpoint.

The current member record limits which selected-agent options the UI offers. The
interface no longer treats a wildcard string alone as permission to manage staff.
These checks improve presentation only. Current backend permission checks remain
authoritative; this is NOT custom-role/team runtime or complete resource policy.

Invitation persistence and email delivery are distinct. Pending invitations with
`deliveryState=sent` receive a sent notification. Failed delivery is shown as
saved-but-failed, and unknown delivery remains unconfirmed. Terminal invitation
states are not described as newly sent. The backend's existing postcommit email
workflow is unchanged; no durable mail worker is added.

## Verification

Executed: 37 Node module checks using actual team/workspace/storage source with
explicit browser/storage/network fixtures; strict TypeScript 5.8.3 checking of the
team transport and unchanged supporting modules under a minimal Vite declaration;
syntax transpilation of four TypeScript/TSX runtime/test files. The normal Vitest
file contains nine cases and the React/Testing Library file contains five cases;
those normal tests were authored but NOT executed in this environment.

Reproduce the isolated module checks after installing frontend dependencies:

```sh
node --test scripts/check_membership_transport.cjs
```

This does not establish React rendering, real cookies, cross-tab session races,
full-project locked-compiler lint/type/build success, backend authentication,
PostgreSQL/RLS or production acceptance. The backend API's existing limitations
must still be addressed and all existing CI gates must pass before merging.

## Separate blocked backend work

A separate prepared backend change rechecked actor/sponsor grants, prevented stale
invitations overwriting existing members, added optional member-version conflicts,
kept organization membership on workspace removal, coupled domain audit/outbox,
fenced old mail delivery results and removed the duplicate invitation handler.
The repository tool blocked the service/schema tree write. That operation was not
retried via a different route, and NONE of those backend changes is in this
client checkpoint. The corresponding 43 isolated checks concern the local review
source, not the current branch. They are delivered separately as review evidence.

In particular, do not claim that this client update fixes pending-invitation role
overwrite, implements server-side version checks, changes organization-member
removal semantics, removes duplicate backend routing, or adds current-sponsor
revalidation. No UI code calls a missing backend API or sends a new version field.
No previously blocked model, migration or router-registration write is retried.
