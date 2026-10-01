# Organization selection and no-workspace recovery

Continuation branch: `feature/workspace-platform-consolidated-20260917`.
Baseline for this change: `d2ad73382cde96445df85262e9d9571f1504556f`.

## Implemented slice

The verified account can open `/organizations`, list its actual organization memberships, select a destination, and return to the existing workspace bootstrap. This does not create tenants, memberships, workspace grants or staff roles. The role in the new session comes from the current destination membership. The old organization membership is not required for recovery into a different still-authorized organization.

`/organization/billing` is an authenticated organization-only frontend route outside the workspace/profile bootstrap. It uses the existing billing endpoints and their server-side permissions. It shows measured subscription/usage data and existing checkout/portal/cancellation/reactivation operations, not fallback subscriptions. A workspace loading failure, missing accessible workspace or incomplete profile no longer hides the organization chooser and billing recovery links. The normal dashboard starter area exposes those links too.

## API contracts

- `GET /api/v1/me/organizations`: verified interactive access token; actual memberships only; keyset pagination using optional `after` UUID; at most 100 entries and `nextCursor`; no workspace header required; no-store response.
- `POST /api/v1/auth/select-organization`: JSON `organizationId`; verified access token plus matching HttpOnly refresh-cookie proof. Non-production CLI clients may supply `refreshToken` instead. Production rejects that body field. The request cannot assign a role, create a membership or choose a workspace.
- Success returns the existing session fields plus `organizationId` and `organizationName`. Production does not return the refresh token in the body. Existing cookie settings are reused.
- Invalid/expired/revoked credentials and stale refresh proof return 401; unverified account or unavailable membership returns 403; rate limit returns 429; session-store/audit/commit failure returns an explicit error. No browser-selected role or caller-supplied workspace identifier is authority.

## Transaction and session behavior

The request locks/rechecks the user and target membership, rechecks credential version and email verification, records a scoped audit event and outbox event, and transfers the refresh proof atomically in Redis. Transfer uses a new family, consumes the exact old family/token, checks access-token revocation and refuses an existing destination key. A late old-family refresh or losing selection replay cannot revoke the new family.

PostgreSQL and Redis are not one transaction. If the database commit fails, compensation conditionally revokes the undelivered new family only when its token matches. It never returns a successful session after an audit/commit failure. A Redis outage has no in-memory authorization fallback for these endpoints. The Lua operation targets the repository's configured standalone Redis topology; a cluster cross-slot error fails closed and is not advertised as cluster support.

The event `organization.session.selected.v1` uses the existing transactional outbox/Kafka publisher. Production deployments that disable automatic topic creation must provision this topic and the appropriate publisher permissions before activation. Its payload includes the actor ID; it does not contain credentials or profile/message content. An event records server-side selection, not proof that the browser received the response.

The frontend rejects stale account responses, prevents duplicate clicks, uses the Web Locks API when available to serialize cooperating tabs, strips refresh tokens before persistence and clears the selected organization's remembered workspace. If a selection response is ambiguous or arrives after another account signed in, access state is cleared and sign-in is required rather than automatically replaying the mutation. Expired access tokens require sign-in for this operation; this slice does not replace the application's general refresh coordination.

## Tests and evidence boundary

Executed during this continuation: 22 isolated Python transfer/claim tests; 23 actual-router ASGI checks using a minimal SQLAlchemy/SQLite host with substituted host services and Redis; 26 Node module checks using the actual organization/workspace transports with in-memory storage/fetch; strict TypeScript checking of those transports with the extracted existing Session declaration; syntax checking of seven changed TypeScript/TSX files; Python compilation.

The normal backend integration file `backend/tests/test_organization_sessions_api.py` adds eight regressions against the real application conftest with only recording Redis/rate-limit adapters. The normal frontend Vitest file adds seven transport regressions. These normal application/Vitest tests were written but were not executed in the limited local source environment. Full CI, React browser rendering, real cookie/cross-tab races, PostgreSQL runtime roles/RLS, real Redis Lua and broker/provider acceptance remain mandatory.

This change does not modify `main`, run production migrations, deploy a server, or mark PR #114 ready to merge. It does not claim completion of custom-role/team runtime, whole-application branding, verified custom domains/senders, lifecycle/export/deletion, budgets or the full specification. The existing migration junction remains unchanged; no new migration is required for this slice.
