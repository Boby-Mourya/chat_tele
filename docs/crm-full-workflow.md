# CRM full workflow: Lead generation to verified external record

This document is the implementation and operations contract for the workspace-scoped Lead-to-CRM workflow.

## Completion boundary

The workflow keeps and extends the existing production architecture. It does not introduce a second Lead store, CRM queue, provider connector layer, retry engine, or Zoho implementation.

Implemented application path:

1. a Lead Generation Agent receives or continues an omnichannel conversation;
2. an authorized workspace user resolves the Conversation;
3. the purpose-aware resolution service creates or reconciles one local Lead;
4. the Lead profile stores normalized identity, source, qualification, campaign, consent, and custom fields;
5. a transactional outbox event requests CRM synchronization;
6. the CRM router evaluates only routes and connections assigned to the Lead's workspace;
7. a deterministic field mapping creates a frozen delivery payload;
8. an idempotent CRM delivery performs create, update, or upsert;
9. provider acknowledgement stores the external record ID;
10. read-back verification proves the provider record without resending an acknowledged write;
11. classified failures enter bounded retry, authentication recovery, mapping recovery, or dead-letter replay;
12. frontend pages expose the same states and recovery actions.

## End-to-end flow

```text
Customer message
    ↓
Verified channel webhook / Widget / API
    ↓
Normalize + deduplicate + store durable event
    ↓
Resolve Tenant + Workspace + Agent
    ↓
Conversation + Message history
    ↓
Agent purpose = lead_generation
    ↓
Qualification and contact enrichment
    ↓
Workspace user selects Resolve
    ↓
ConversationResolutionService locks and resolves Conversation
    ↓
Create/reconcile exactly one Lead
    ↓
Create/reconcile LeadProfile and Contact identity
    ↓
LeadActivityEvent + transactional outbox
    ↓
lead.crm.sync.requested.v1
    ↓
WorkspaceCRMRouteService
    ├── Lead workspace boundary
    ├── enabled route conditions
    ├── assigned connection
    ├── auto-sync policy
    └── inbound-origin loop prevention
    ↓
CRMDelivery (idempotent)
    ↓
Canonical Lead mapping → provider payload
    ↓
Provider create / update / upsert
    ├── rejected before ACK → classified write retry
    └── accepted
          ↓
       external_record_id + acknowledged_at
          ↓
       read-back verification
          ├── verified → CRMExternalReference + verified_at
          ├── temporary read failure → verification-only retry
          └── exhausted → dead letter / operator replay
```

## Backend implementation map

### 1. Conversation resolution and local Lead creation

Entry points:

- `POST /api/v1/conversations/{conversation_id}/resolve`
- `PATCH /api/v1/conversations/{conversation_id}` with `state=resolved`

Files:

- `backend/src/northstar_api/routers/conversations.py`
- `backend/src/northstar_api/services/conversation_resolution.py`

`ConversationResolutionService.resolve()`:

- reads the authoritative Agent purpose;
- keeps Conversation and Message records;
- marks the Conversation resolved;
- locks/reconciles the Lead by `tenant_id + workspace_id + conversation_id`;
- creates the Lead only for Lead Generation Agents by default;
- enriches `Lead.fields_json` with source channel, resolution, public Conversation ID, and resolution time;
- ensures the Lead profile and contact identity;
- emits `lead.captured.v1`, `lead.created.v1`, and `lead.crm.sync.requested.v1`;
- remains idempotent when Resolve is repeated.

### 2. Canonical Lead domain

Files:

- `backend/src/northstar_api/models.py`
- `backend/src/northstar_api/lead_crm/models.py`
- `backend/src/northstar_api/lead_crm/services.py`
- `backend/src/northstar_api/routers/leads.py`
- `backend/src/northstar_api/routers/qualification.py`

Local data includes:

- Tenant, Workspace, Agent, Conversation and channel;
- contact name, email, phone, normalized identities;
- lifecycle and qualification status;
- score and qualification reason;
- source provider and external identity;
- campaign, advertisement and UTM fields;
- consent;
- arbitrary custom fields;
- activity history and correlation IDs.

### 3. Transactional event and router

Files:

- `backend/src/northstar_api/services/outbox.py`
- `backend/src/northstar_api/workers/outbox_publisher.py`
- `backend/src/northstar_api/workers/crm_router_consumer.py`
- `backend/src/northstar_api/lead_crm/workspace_routing.py`

The router:

- loads the Lead in tenant scope;
- evaluates only `WorkspaceCRMRoute` rows for `Lead.workspace_id`;
- evaluates channel, provider, campaign, score, qualification and Agent conditions;
- honors `auto_sync_new_leads` and `auto_sync_updates`;
- suppresses the inbound origin connection to prevent webhook loops;
- creates one delivery per selected connection;
- calculates an idempotency key from tenant, workspace, Lead, connection, operation and payload hash;
- publishes `lead.crm.delivery.created.v1`.

### 4. Mapping and provider delivery

Files:

- `backend/src/northstar_api/lead_crm/mapping.py`
- `backend/src/northstar_api/lead_crm/connectors.py`
- provider modules under `backend/src/northstar_api/lead_crm/`
- `backend/src/northstar_api/workers/crm_delivery_worker.py`

The delivery worker:

- locks queued/retryable deliveries;
- uses the stored mapping version;
- persists a frozen mapped payload and payload hash;
- invokes provider create/update/upsert capability;
- records immutable attempt history;
- classifies authentication, authorization, validation, mapping, duplicate, rate limit, timeout, network, unavailable, and configuration failures;
- never treats an empty or malformed provider response as positive acknowledgement;
- stores provider HTTP status, provider code and request ID without storing credentials.

### 5. ACK and read-back verification

Files:

- `backend/src/northstar_api/workers/crm_reconciliation.py`
- `backend/src/northstar_api/lead_crm/models.py`
- `backend/src/northstar_api/routers/crm_delivery_attempts.py`

The platform separates:

- **write success**: the provider returned a positive external record ID;
- **read-back success**: a later GET proves that record exists;
- **mapped-field proof**: configured fields match when the connector supports comparison.

An acknowledged write is never blindly resent because read-back failed. Retry after acknowledgement is verification-only.

### 6. Inbound CRM webhooks

Files:

- `backend/src/northstar_api/routers/crm_webhooks.py`
- `backend/src/northstar_api/workers/crm_webhook_consumer.py`
- CRM webhook models, conflict policy and audit components under `lead_crm`.

The inbound path:

- verifies the provider signature;
- stores and deduplicates the raw event;
- correlates the external record with a local Lead;
- applies the configured conflict policy;
- records no-op echoes instead of re-emitting unchanged updates;
- records the provider connection as change origin;
- prevents the resulting update from being routed back to the same connection.

### 7. Operations, recovery and audit

Files:

- `backend/src/northstar_api/routers/crm_operations.py`
- `backend/src/northstar_api/routers/crm_dead_letters.py`
- `backend/src/northstar_api/routers/crm_health_history.py`
- `backend/src/northstar_api/routers/crm_webhook_events.py`
- `backend/src/northstar_api/workers/crm_health_monitor.py`
- `backend/src/northstar_api/lead_crm/audit.py`

Operations include:

- connection health and historical snapshots;
- worker probes and queue depth;
- delivery attempt history;
- mutation audit;
- webhook activity;
- incident notifications;
- dead-letter details;
- replay and cancellation controls.

## Live workflow API

Endpoint:

```http
GET /api/v1/crm/workflow?limit=50
Authorization: Bearer <access-token>
X-Workspace-ID: <active-workspace-id>
```

Permission:

```text
crm.view
```

Files:

- `backend/src/northstar_api/routers/crm_workflow.py`
- `backend/src/northstar_api/services/crm_workflow.py`
- `backend/src/northstar_api/lead_crm/crm_workflow_schemas.py`

The response contains no credentials, mapped payload, idempotency key, provider response body, or secret configuration.

It returns:

- readiness for Lead Generation Agent, CRM connection, field mapping, routing, auto-sync and provider health;
- counts of resolved Conversations, local Leads, in-flight deliveries, verified records, attention states and open dead letters;
- delivery counts by state;
- workspace connection configuration and health;
- recent Lead journeys with the latest delivery;
- provider acknowledgement and verification proof;
- deterministic next actions.

## Frontend implementation map

### CRM Workflow page

Route:

```text
/crm-workflow
```

Files:

- `frontend/src/pages/CRMWorkflowPage.tsx`
- `frontend/src/pages/CRMWorkflowPage.css`
- `frontend/src/lib/crm-workflow-api.ts`
- `frontend/src/App.tsx`
- `frontend/src/components/app-shell.tsx`

The page provides:

- automatic-workflow readiness;
- the eight-stage frontend/backend execution path;
- workspace CRM connection readiness;
- delivery-state distribution;
- recent Lead journeys;
- external record ID, acknowledgement and verification state;
- write and read-back attempt counts;
- errors without secrets;
- direct navigation to Agents, Conversations, Leads and Integrations for remediation.

### Existing Lead operations

File:

- `frontend/src/pages/LeadsPage.tsx`

The Lead detail remains the operator surface for:

- manual sync;
- provider delivery status;
- external record ID;
- provider ACK;
- read-back verification;
- write attempt history;
- verification-only retry;
- activity history.

### Existing CRM setup and operations

Files:

- `frontend/src/pages/IntegrationsPage.tsx`
- `frontend/src/components/crm-management-panel.tsx`
- `frontend/src/lib/lead-crm-api.ts`

The Integrations area remains the configuration and recovery surface for:

- provider setup and OAuth;
- safe connection switching;
- schema discovery;
- field mapping;
- routing rules;
- auto-sync settings;
- health and historical incidents;
- webhook activity;
- audit;
- dead-letter replay.

## Delivery state contract

```text
created
  → routed
  → queued
  → processing
  → sent / acknowledged
  → verifying
  → verified
```

Recoverable paths:

```text
processing
  → retrying / rate_limited / auth_required / mapping_error / failed
  → queued / processing
  → acknowledged
  → verifying
  → verified
```

Terminal operator paths:

```text
retrying / rate_limited / auth_required / mapping_error / failed
  → dead_letter
  → replay → retrying
  → cancelled
```

## Failure-to-action matrix

| State | Meaning | Required action |
| --- | --- | --- |
| `auth_required` | Credential expired, revoked or cannot be decrypted | Reconnect the CRM |
| `mapping_error` | Canonical Lead cannot be mapped to required provider fields | Repair and validate mapping |
| `rate_limited` | Provider asked the platform to slow down | Respect retry timing; do not duplicate |
| `retrying` | Bounded write or verification retry is scheduled | Observe; manually retry only when justified |
| `acknowledged` | Provider record ID exists | Run verification only |
| `verifying` | Read-back check is running | Do not resend write |
| `failed` | Classified non-terminal failure | Review attempt history and retry policy |
| `dead_letter` | Retry policy exhausted | Replay or cancel with audit evidence |
| `verified` | External record was proven | No recovery action |

## Security and tenancy

Every administrative request is:

- authenticated;
- scoped by Tenant;
- scoped by active `X-Workspace-ID`;
- permission checked;
- filtered by Agent access where applicable.

Secrets stay encrypted in backend storage and are never returned by the workflow API. Native outbound connectors enforce provider URL and SSRF policy. Provider signatures, event hashes, idempotency keys, origin guards and audit events protect the inbound and outbound paths.

## Automated acceptance

Backend tests:

```text
backend/tests/test_crm_workflow.py
```

They verify:

- unconfigured readiness blockers;
- workspace scoping;
- Lead Generation Agent readiness;
- configured connection, mapping, route and auto-sync;
- resolved Conversation and local Lead counts;
- verified delivery and external ID;
- omission of credentials, payload and idempotency key.

Frontend tests:

```text
frontend/src/lib/crm-workflow-api.test.ts
frontend/src/pages/CRMWorkflowPage.test.tsx
```

They verify:

- bearer and active-workspace headers;
- normalized API errors;
- complete eight-stage workflow presentation;
- readiness, connection and journey rendering;
- provider proof and qualification display;
- refresh behavior;
- deterministic setup actions for blocked workflows.

## Live-provider acceptance boundary

The code path supports the registered provider contracts, but a provider is only called **live-verified** after its authorized sandbox account has passed:

1. connection and token refresh;
2. schema discovery;
3. create/update/upsert;
4. positive external record ID;
5. read-back verification;
6. mapped-field comparison where supported;
7. invalid credential handling;
8. rate-limit behavior;
9. duplicate/idempotency behavior;
10. inbound webhook and loop-prevention behavior.

Untested provider accounts remain explicitly pending. Customer production data must not be used for smoke testing.
