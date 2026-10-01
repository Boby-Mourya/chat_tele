# Workspace refresh and editor-state preservation

Branch: `feature/workspace-platform-consolidated-20260917`.
Source baseline: `c052fe67e2174f7f7ce7fc0a2f28a0cfce9d9eb7`.
This continuation changes the existing frontend context pipeline only. It requires no database migration or unpublished branding/access models.

## Runtime behavior

The workspace provider and setup gate use a stable presentation key instead of treating every access-token string as a new account. The key contains the existing user/organization cache namespace, organization role, credential version and email-verification state. It is derived from browser session data solely to partition UI state; it grants no access and never replaces server authentication, current membership, permissions or entitlements.

A routine token refresh for the same identity preserves mounted children and unsaved local form state. Organization, identity, role, credential-version or verification changes invalidate that presentation key. The existing route and backend checks still apply. Workspace selection remains tab-local; the API header remains only a selector.

An in-flight workspace GET whose token was externally refreshed may retry exactly once with the new token, but only while the original presentation key and relevant workspace remain unchanged. The request never initiates token refresh itself. A second token rotation or a changed context cancels the result. POST/PATCH requests are never automatically replayed: a token change during a write yields an explicit uncertain-outcome cancellation and the caller must reload server state before retrying.

Workspace list requests support AbortSignal. The provider cancels replaced requests on context changes, workspace selection and unmount, and retains its generation checks for transports that resolve after cancellation. Protected reads are no-store.

An explicit refresh does not replace an already loaded view with the initial loading screen. Transient network/5xx failures during a same-context refresh show a retry warning while retaining that previously loaded view. Initial-load failures and authorization/context failures do not use stale account data. A 401/403/409/428/429 is not treated as a transient network outage. Actual API requests still decide whether every action is allowed.

The setup gate follows the same distinction. Same-context bootstrap revalidation, including after token rotation, does not unmount an editor. A credential/role/organization change still clears its old context. Cancellation from a superseded bootstrap is not displayed as a new account error.

## Verification

Executed locally: 31 Node tests against the actual workspace transport with explicit storage, window and fetch fixtures; strict TypeScript checking of that transport and the unchanged storage helper using TypeScript 5.8.3 and a minimal Vite declaration; syntax transpilation of the five changed TypeScript/TSX source/test files.

The repository additionally contains six Vitest transport regressions and six React/Testing Library regressions for token rotation, pending refresh, transient outages, authorization denial and credential-version changes. Those normal Vitest/React tests were written but were not executed in this restricted environment. The Node fixtures are not a real browser, refresh-cookie race test, React renderer, backend authorization test or complete production build.

Reproduce the isolated transport checks after installing the frontend dependencies:

```sh
node --test scripts/check_workspace_refresh.cjs
```

Use the repository's existing lint, typecheck, Vitest, backend, security, deployment and integration gates before merging. None is disabled or treated as passed by these isolated checks.

## Unpushed branding work

A separate workspace branding publication implementation was prepared locally during this continuation, with 44 isolated backend/SQLite checks and 23 client-module checks. The repository tool blocked the tree-write request containing its new branding tables and migration because it could not determine the request's safety status. That blocked operation was not retried through another route. No publication models, migration, endpoints, observer or replacement editor from that attempt are part of this commit; the existing basic branding editor remains in use.

The broader specification is unfinished. In particular, this refresh change is not versioned branding, organization inheritance, verified domains/senders, full custom-role/team enforcement, workspace lifecycle, quotas/budgets or production acceptance. PR #114 remains a draft and main is not modified.
