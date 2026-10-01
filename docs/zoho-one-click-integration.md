# Zoho CRM one-click integration

## Completion contract

The Zoho card on **Integrations** is the primary setup path. A workspace administrator clicks **Connect Zoho**, grants consent in Zoho, and returns to the application. The callback completes all remaining work automatically:

1. Create or reuse one Zoho connection for the active workspace.
2. Encrypt the platform OAuth client credentials and the customer refresh token at rest.
3. Enable automatic synchronization for new leads and updates.
4. Create or repair the default workspace CRM route.
5. Test the Zoho API and persist a health snapshot.
6. Discover the live `Leads` field metadata.
7. Generate and activate a mapping using field API names.
8. Add safe constants for supported mandatory custom fields.
9. Upsert a real certification lead with CRM automations suppressed.
10. Persist the Zoho acknowledgement and external record ID.
11. Read the lead back from Zoho and verify `Email`, `Last_Name`, and `Company`.
12. Mark the integration healthy only after the end-to-end proof succeeds.

No workspace user enters a Zoho password, OAuth client secret, refresh token, or access token in the browser.

## One platform setup required before customers can click Connect

Create a **server-based OAuth client** in the Zoho API Console for each deployed Northstar environment. Register this exact callback:

```text
https://YOUR_API_HOST/api/v1/crm/zoho/one-click/callback
```

Copy `docs/zoho-one-click.env.example` into the environment/secret manager and set `ZOHO_CLIENT_ID`, `ZOHO_CLIENT_SECRET`, `ZOHO_OAUTH_FRONTEND_URL`, and `ZOHO_OAUTH_REDIRECT_URI`.

The customer’s normal Zoho email/password is intentionally not accepted by the integration. The password must stay inside Zoho’s login page; Northstar receives an authorization code and exchanges it for encrypted OAuth tokens.

## Data centers

Use matching domains for the Zoho account data center. Examples:

| Data center | Accounts URL | API domain |
|---|---|---|
| United States | `https://accounts.zoho.com` | `https://www.zohoapis.com` |
| India | `https://accounts.zoho.in` | `https://www.zohoapis.in` |
| Europe | `https://accounts.zoho.eu` | `https://www.zohoapis.eu` |
| Australia | `https://accounts.zoho.com.au` | `https://www.zohoapis.com.au` |
| Japan | `https://accounts.zoho.jp` | `https://www.zohoapis.jp` |

Configure one deployment for the intended data center. Multi-data-center tenant selection can be added later without changing the OAuth or delivery contract.

## Live certification record

The callback upserts a stable lead using an email like:

```text
northstar.crm.cert.<connection-prefix>@example.com
```

It uses `trigger: []`, so the certification request does not intentionally run Zoho workflows, approvals, or blueprints. The record description identifies it as an automated Northstar certification record and says it may be archived or deleted.

The application stores only safe evidence in the connection configuration:

- certification status;
- external Zoho record ID;
- provider request ID/code when available;
- verified field names;
- verification timestamp.

It never stores OAuth tokens, the OAuth client secret, or browser credentials in certification evidence or API responses.

## Runtime lead flow after connection

```text
Message / API / manual lead
        ↓
Workspace + agent resolution
        ↓
Qualification and local Lead/LeadProfile
        ↓
Transactional CRM event
        ↓
Workspace route selects Zoho
        ↓
Active mapping builds frozen payload
        ↓
Idempotent Zoho upsert
        ↓
Provider acknowledgement + external record ID
        ↓
Read-back verification
        ↓
Verified, retry, authentication recovery, or dead letter
```

Automatic sync is enabled for both new leads and updates. Existing delivery workers retain bounded retries, provider error classification, refresh-token handling, read-back verification, attempt history, audit events, and dead-letter recovery.

## API surface

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/api/v1/crm/zoho/one-click/status` | Read workspace readiness without exposing secrets |
| `POST` | `/api/v1/crm/zoho/one-click/start` | Create/repair connection and return Zoho authorization URL |
| `GET` | `/api/v1/crm/zoho/one-click/callback` | Exchange code, bootstrap mapping/route, run live proof, redirect to UI |
| `POST` | `/api/v1/crm/zoho/one-click/certify` | Re-run schema discovery, mapping, upsert, and read-back |

## Acceptance test

1. Deploy with the environment variables above and a strong `CRM_CREDENTIAL_ENCRYPTION_KEY`.
2. Sign in as a workspace administrator.
3. Open **Integrations** and click **Connect Zoho**.
4. Choose the intended Zoho CRM organization and approve access.
5. Confirm the application returns to Integrations with **Live and verified**.
6. Confirm the card displays the external Zoho lead ID.
7. Open Zoho CRM Leads and confirm the `Northstar CRM Certification` record exists.
8. Create or resolve a normal lead in Northstar.
9. Confirm its workflow progresses to `verified` and the Zoho external record ID appears in the lead detail.
10. Disable or revoke Zoho authorization and confirm the connection changes to `auth_required` rather than silently losing leads.
