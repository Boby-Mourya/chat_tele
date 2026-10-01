# Current frontend and backend connection review

Date: 2026-09-15

## Result

The current frontend is running with the real API and existing database.
The public ngrok endpoint forwards to the rebuilt Docker web service on port
3100, which proxies `/api/` to the API container. The development server on
5176 also proxies to the real API on port 8100 with demo mode disabled.

Real local sign-in, saved agents, and integration status loading passed.
The current Integrations page shows Zoho CRM and WhatsApp as connected.
These are backend-reported connection states; this review did not send a new
WhatsApp message or create a CRM record to test external delivery.

## Last five commits by the configured repository author

All five commits are ancestors of the current checkout. The intervening merge
and its PDF ingestion changes remain present.

| Commit | Change reviewed |
| --- | --- |
| `e0ebcd4` | Current frontend changes, route error handling and dashboard theme |
| `3ffe75a` | Online courses dashboard design across the frontend |
| `8d15673` | WhatsApp activation, number assignment and settings recovery |
| `eec9438` | WhatsApp welcome messages and channel-specific reply controls |
| `1bc7b3a` | Education conversations kept separate from leads and CRM |

SHA-256 checks matched all 24 checked backend files in the running API container
to the current workspace: backend source touched by these commits plus the
recovered migration.

## Repairs

- Restored the original `0043_knowledge_training.py` from the older running
  container. Its hash matches the recovered source exactly. The database had
  already applied this revision, but the checkout lacked the migration file.
- Backed up the existing database before recovery. Verified the complete
  migration sequence in a separate database. The existing Help Center schema,
  indexes, grants and isolation policies match the freshly migrated schema.
  Its branch is already merged into revision 0011; the final database revision
  remains `0043_knowledge_training`, matching the repository head.
- Rebuilt and started the current web, API and configured workers.
- Made demo fallback explicitly opt-in across the API clients. Backend failures
  no longer silently become demo data when the mode is unspecified.
- Ignore saved demo authentication in real-backend mode, requiring real sign-in.
- Made Vite read the API proxy destination from the frontend environment file.
- Returned ngrok to the rebuilt web service and verified the configured public
  callback URLs through the normal ngrok launcher.

## Verification

| Check | Result |
| --- | --- |
| Current frontend build and TypeScript checks | Passed |
| Recent-commit frontend regressions and session-switch tests | 65 passed across 9 files |
| Recent-commit backend regressions | 39 passed across 11 files |
| Fresh database migration sequence | Passed |
| Local authenticated browser checks | 13 main routes, no JavaScript errors |
| Local data endpoints | Agents, conversations, analytics, integrations, CRM providers/connections and channels returned 200 |
| Public routing without credentials | HTML matches local production build, asset 200, health `ok`, protected API 401 |
| Runtime | Web, API and infrastructure health checks passed; configured workers running |

The local browser sees expected 403 responses when probing platform-admin access
with a workspace owner account; the UI correctly withholds that separate role.
Detailed logs and screenshots are in ignored `reports/recovery/`.

## Remaining verification limits

The full repository checks are **not clean**. The broader frontend run had
395 passes and 26 failures; lint reported 43 errors and one warning. The broader
backend run from its project directory had 415 passes, 62 failures and six errors.
Examples include outdated WhatsApp test mocks missing the accounts API, tests
expecting old UI labels or implicit demo fallback, shared test data hitting plan
limits, missing workspace IDs in old fixtures, and Windows temporary-directory
permissions. These results are not replaced by the narrower passing regressions.

Authenticated checks used localhost only. Automatic approval review rejected
submitting the stored administrator password to the public ngrok URL, so public
verification checked routing and assets without credentials.

External provider delivery, every write workflow and uploads from another
computer were not certified. Object storage still uses the existing localhost
public endpoint, which needs a reachable upload origin for other computers.

## Running this version

Use `start.bat` to rebuild and start the connected app and ngrok. Keep Docker,
ngrok and this computer running. Refresh the public page and sign in with your
real account; an old demo session cannot authenticate to the backend.
