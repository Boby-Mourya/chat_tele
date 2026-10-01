# Lead + CRM implementation status

Last reviewed against the current repository architecture: 2026-09-13.

## Delivery decision

The Lead and CRM foundation is preserved. The platform does not introduce a second Lead store, CRM router, provider queue, retry engine, or Zoho implementation.

This delivery completes the missing coherent product surface across the existing backend and frontend:

```text
Conversation
→ purpose-aware Resolve
→ one local Lead
→ Lead profile and qualification
→ transactional CRM sync event
→ workspace route
→ mapped idempotent delivery
→ provider ACK and external record ID
→ read-back verification
→ retry / dead letter / replay
```

## Completion matrix

| Area | Status | Evidence |
| --- | --- | --- |
| Tenant and Workspace isolation | Complete | All Lead, route, connection and delivery queries include tenant/workspace scope |
| Agent access restriction | Complete | Workflow counts and journeys honor the principal's allowed Agent IDs |
| Lead Generation Agent purpose | Complete | Active `lead_generation` readiness and purpose-aware resolution |
| Conversation Resolve → Lead | Complete | Idempotent Conversation lock and one Lead per Conversation |
| Local Lead profile | Complete | Identity, lifecycle, qualification, channel, campaign, consent and custom fields |
| CRM provider registry | Complete | Zoho, Salesforce, HubSpot, Dynamics 365, Pipedrive, Freshsales, REST and webhook contracts |
| Workspace CRM connection | Complete | Connection assignment and auto-sync settings |
| OAuth/reconnect | Complete | Provider OAuth and safe connection switching |
| Schema discovery | Complete | Provider field schema retrieval |
| Field mapping | Complete | Versioned canonical Lead mapping |
| Routing | Complete | Workspace route conditions and origin-loop suppression |
| Durable delivery | Complete | Idempotent CRM delivery and frozen payload |
| Provider ACK | Complete | Positive external record ID required |
| Read-back verification | Complete | Verification separated from write retry |
| Delivery attempts | Complete | Write and verification attempt evidence |
| Error classification | Complete | Auth, validation, mapping, duplicate, rate-limit, timeout, network, unavailable and configuration |
| Dead-letter recovery | Complete | List, detail, replay and cancellation paths |
| Inbound CRM webhook | Complete | Verification, deduplication, conflict policy, no-op guard and loop prevention |
| Health and operations | Complete | Health snapshots/history, worker probes, incidents, notifications and audit |
| Lead frontend | Complete | Lead list, filtering, manual sync, ACK, external ID, verification and retries |
| CRM setup frontend | Complete | Connections, OAuth, schema, mapping, routes, auto-sync, health, audit and DLQ |
| Full CRM workflow frontend | Complete in this delivery | Readiness, eight-stage flow, counters, connection state and recent Lead journeys |
| Full CRM workflow backend API | Complete in this delivery | `GET /api/v1/crm/workflow` |
| Backend workflow tests | Added in this delivery | `backend/tests/test_crm_workflow.py` |
| Frontend workflow tests | Added in this delivery | API and page test suites |
| Final repository CI for this delivery | Pending execution | Must run on the final branch/head before release certification |
| Authorized live-provider sandbox matrix | Environment-dependent | Must remain separately labelled per provider/account |

## Newly completed workflow API

```http
GET /api/v1/crm/workflow?limit=50
```

The endpoint requires `crm.view` and the active `X-Workspace-ID`.

It returns:

- automatic-workflow readiness;
- resolved Conversation, local Lead, delivery, verification and dead-letter counts;
- delivery distribution across the full CRM state machine;
- workspace connection configuration and health;
- recent Lead journeys;
- provider acknowledgement and verification proof;
- deterministic next actions;
- no credentials, delivery payload, idempotency key or provider response body.

## Newly completed frontend

Route:

```text
/crm-workflow
```

The page is part of primary navigation and shows:

1. Conversation capture;
2. Resolve and qualification;
3. local Lead creation;
4. durable CRM routing;
5. field mapping;
6. provider upsert;
7. provider acknowledgement;
8. read-back verification or recovery.

It also shows current workspace blockers, configured CRM connections, status distribution and recent Lead journeys.

## Branch reconciliation

Historical CRM hardening branches already contained in `main` are not merged a second time. Archive, duplicate and stale branches are not promoted merely to reduce branch count.

The full CRM workflow delivery is developed from the current `main` boundary in:

```text
feature/crm-full-workflow
```

It is eligible for `main` only as one complete unit: backend, frontend, tests and documentation.

## Release rule

The module is considered source-complete when all files above are committed together. Release certification additionally requires the final-head CI jobs to actually execute:

- backend Ruff;
- backend format check;
- MyPy;
- backend tests and coverage;
- frontend ESLint;
- TypeScript;
- frontend tests;
- frontend build;
- architecture/configuration checks;
- source and image security checks;
- disposable topology smoke;
- CodeQL where repository policy and entitlement allow it.

A GitHub Actions job that is created with zero steps and no runner is an infrastructure/account condition, not a passing test and not an application failure.

## Live-provider rule

No provider is represented as live-verified without an authorized sandbox execution. The source implementation can be complete while provider-account acceptance remains explicitly pending. That acceptance must use approved synthetic records rather than customer production data.
