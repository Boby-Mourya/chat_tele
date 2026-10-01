# One-click CRM integration

## Outcome

A Workspace administrator selects a CRM, approves the provider consent screen (or enters the CRM API key for Freshsales/customer REST), and Northstar completes the remaining setup automatically:

1. Create or reuse the Workspace-scoped CRM connection.
2. Encrypt credentials server-side.
3. Test authentication and provider health.
4. Discover the Lead/contact schema where supported.
5. Generate and activate a provider-correct field mapping.
6. Enable an all-eligible-Leads Workspace route.
7. Enable automatic new-Lead and Lead-update synchronization.
8. Queue a paginated backfill for eligible existing Leads.
9. Send a live acceptance-test Lead.
10. Require provider acknowledgement, an external record ID and read-back identity proof before showing **Live certified**.

A successful OAuth callback does not by itself count as certification. `liveCertified=true` is only returned after a persisted `CRMDelivery` reaches `verified` with an external CRM record ID.

## Supported providers

| Provider | Customer action | Platform-managed setup | Read-back proof |
|---|---|---|---|
| Zoho CRM | Approve OAuth | Yes | Yes |
| Salesforce | Approve OAuth | Yes | Yes |
| HubSpot | Approve OAuth | Yes | Yes |
| Microsoft Dynamics 365 | Enter organization URL, then approve OAuth | Yes | Yes |
| Pipedrive | Approve OAuth | Yes | Yes |
| Freshsales | Enter account base URL and API key | Encrypted direct connection | Yes |
| Generic REST CRM | Enter standard HTTPS paths and credential | Encrypted direct connection | Yes |

## Platform OAuth application configuration

Register these exact callback URLs in each provider application. Replace `https://api.example.com` with `CRM_OAUTH_PUBLIC_BASE_URL`.

```text
https://api.example.com/api/v1/crm/oauth/zoho/callback
https://api.example.com/api/v1/crm/oauth/salesforce/callback
https://api.example.com/api/v1/crm/oauth/hubspot/callback
https://api.example.com/api/v1/crm/oauth/dynamics365/callback
https://api.example.com/api/v1/crm/oauth/pipedrive/callback
```

Configure server-side environment variables:

```dotenv
CRM_CREDENTIAL_ENCRYPTION_KEY=<independent strong encryption key>
CRM_OAUTH_PUBLIC_BASE_URL=https://api.example.com
CRM_OAUTH_FRONTEND_ORIGIN=https://app.example.com

CRM_ZOHO_CLIENT_ID=
CRM_ZOHO_CLIENT_SECRET=
CRM_SALESFORCE_CLIENT_ID=
CRM_SALESFORCE_CLIENT_SECRET=
CRM_HUBSPOT_CLIENT_ID=
CRM_HUBSPOT_CLIENT_SECRET=
CRM_DYNAMICS365_CLIENT_ID=
CRM_DYNAMICS365_CLIENT_SECRET=
CRM_PIPEDRIVE_CLIENT_ID=
CRM_PIPEDRIVE_CLIENT_SECRET=

KAFKA_ENABLED=true
BACKGROUND_DISPATCH_ENABLED=true
```

Client secrets are never accepted from or returned to the one-click browser flow. They are deployment secrets shared by the platform OAuth application. Customer access/refresh tokens are encrypted using the existing CRM credential store.

## Runtime Lead flow

```text
Channel/API/Manual Lead
  -> canonical Lead + LeadProfile
  -> transactional outbox: lead.crm.sync.requested.v1
  -> CRM router
  -> Workspace route + active field mapping
  -> idempotent CRMDelivery
  -> delivery worker
  -> provider ACK + external record ID
  -> read-back verification
  -> verified / bounded retry / dead letter
```

Existing eligible Leads are processed through `crm.connection.backfill.requested.v1` in keyset-paginated batches. The same delivery idempotency key prevents duplicate CRM records when setup is repaired or backfill is requested again.

## Readiness contract

`GET /api/v1/crm/connections/{connection_id}/readiness` reports `ready=true` only when all of the following are true:

- encrypted credentials exist;
- provider health is `healthy`;
- schema is discovered when the connector supports schema discovery;
- the Lead mapping is active;
- an enabled Workspace route targets the connection;
- automatic new-Lead sync is enabled;
- automatic update sync is enabled;
- Kafka and background dispatch are enabled.

`liveCertified=true` additionally requires a verified provider delivery and external CRM record ID.

## Acceptance test

The Integrations page automatically queues a CRM acceptance-test Lead after connection. It polls the exact delivery ID, not an old successful delivery. The test succeeds only after:

1. provider write accepted;
2. external record ID stored;
3. read-back GET returns the same record identity;
4. delivery status becomes `verified`.

If the Workspace has no Agent, a dedicated internal **CRM Acceptance Test Agent** is created automatically so setup is not blocked. The generated Lead is visibly marked as an integration test.

## Generic REST contract

The customer CRM must expose public HTTPS endpoints for:

- health: `GET <baseUrl><healthPath>`;
- upsert/create: `POST <baseUrl><upsertPath>`;
- update: `PATCH <baseUrl><getPath with {id}>`;
- read-back: `GET <baseUrl><getPath with {id}>`.

The write response must contain the external record ID at `externalIdPath`. The read-back response must expose the same ID at `readBackIdPath`. Redirects and private/non-public destinations are rejected by the existing safe outbound HTTP layer.

## Operations

The existing CRM operations UI remains available for health history, attempts, webhook events, retry state and dead letters. A provider acknowledgement is irreversible: read-back retries never resend an acknowledged write.
