# Northstar AI Platform

Telegram managed-bot Connect/Disconnect setup: [platform and customer guide](docs/telegram-managed-bots.md).

Northstar is a multi-tenant AI support platform for creating grounded assistants, managing knowledge, reviewing conversations, deploying website/WhatsApp experiences, capturing leads, and integrating external business systems. The repository contains a React control plane and a FastAPI service backed by PostgreSQL/pgvector, Redis, RabbitMQ, Kafka, and S3-compatible object storage.

The default Docker Compose topology is a production-shaped local environment: it exercises migrations, background workers, transactional event delivery, analytics consumption, persistent volumes, health gates, and the same reverse-proxy path used by the browser. It is intentionally single-node and is not a substitute for a highly available production deployment.

## Lead + Omnichannel + Any-CRM implementation

Active implementation branch: **`feature/lead-crm-omnichannel-platform`**  
Status: **IN PROGRESS / RELEASE BLOCKED — NOT MODULE COMPLETE**  
Draft pull request: **[#30](https://github.com/ooarchitect92/Chat/pull/30)**

Detailed tracker: **[docs/lead-crm-implementation-status.md](docs/lead-crm-implementation-status.md)**  
Architecture invariants: **[docs/architecture/LEAD_CRM_NON_NEGOTIABLES.md](docs/architecture/LEAD_CRM_NON_NEGOTIABLES.md)**  
Implemented verification/recovery behavior: **[runbook](docs/operations/crm-delivery-verification.md)**

The target architecture is:

```text
ANY CHANNEL
    ↓
CHANNEL CONNECTOR
    ↓
CANONICAL EVENT
    ↓
CONTACT / IDENTITY
    ↓
CONVERSATION
    ↓
LEAD QUALIFICATION
    ↓
CANONICAL LEAD
    ↓
TRANSACTIONAL OUTBOX
    ↓
CRM ROUTING
    ↓
DURABLE CRM DELIVERY
    ↓
CRM CONNECTOR
    ↓
ANY CRM
```

### Verified implementation checkpoint

Code commit `f650e7379e990d380e0eb2de2e2613eba371a34a` passed [CI run 34257700348](https://github.com/ooarchitect92/Chat/actions/runs/34257700348). That run tested the PR merge, not a production deployment.

| Area | Verified result | Boundary |
| --- | --- | --- |
| Frontend | Lint, strict types, tests and production build passed | Full requested CRM wizard/lead-detail UX acceptance remains |
| Backend | Ruff, format, mypy and **107 tests passed** | Includes **25 new CRM acceptance cases**; overall line coverage is **56%**, not complete module acceptance |
| Delivery/verification | Persisted ACK, positive record-ID proof, GET-only verification retry, separate budgets, payload revision deduplication and recovery guards tested | Injected recording connector and SQLite; no live-provider claim |
| UI evidence | Separate ACK/verification status, proof scope, read-back attempts/errors and verification-only retry | Seven new presentation tests; broader UX and race validation remain |
| Deployment | Compose/Kubernetes configuration, application/image scans, Docker smoke and migration/API/column checks passed | Migration head `0010_crm_verification`; not a production upgrade or Kubernetes cluster acceptance |
| Source/secret security | Configured Gitleaks and Trivy checks passed | Native outbound hardening and full RLS/security matrix still require acceptance |
| CodeQL | **Blocked**: GitHub rejects SARIF publishing because code scanning is disabled | Administrator action and findings review tracked in [#31](https://github.com/ooarchitect92/Chat/issues/31) |
| Native CRM connectors | Zoho, Salesforce, HubSpot, Dynamics, Pipedrive and Freshsales code is committed | Full contract/fault tests and authorized live-account verification remain pending |

Provider acknowledgement and read-back verification are independent. A verification failure must not resend an acknowledged write. Unsupported read-back stays **acknowledged / verification unsupported**, not verified. Default positive proof matches record identity; explicitly configured `verificationFields` additionally compares transmitted values.

**Remaining work is not limited to CodeQL.** The tracker retains the full requested UX, native provider/security contract matrix, channel qualification and bidirectional sync acceptance, production RLS/concurrency, real broker fault injection, operational audit/health/DLQ completeness, upgrade/backfill validation and live-provider gates. Do not merge or label the full module complete merely because this CI checkpoint is green. Documentation-only changes after the checkpoint do not imply that their own checks already passed.

**Important verification policy:** connector code without usable provider-account evidence remains **LIVE-VALIDATION-PENDING**. Registered/importable connectors are not automatically code-complete or live-verified. The detailed tracker is the source of truth for completed, in-progress, pending and blocked work.

## Security notice

An NVIDIA credential and a third-party account password were exposed in the original project request. Treat both as compromised: revoke/rotate them with their respective providers before running this application. Neither exposed value is stored in this repository.

Never commit `.env`, credentials, exported customer data, or browser-audit artifacts. For production, inject secrets from a secrets manager and set the hardened flags described in [Security](docs/security.md#production-baseline).

CRM integration credentials must be supplied through the credential-store abstraction. The local encrypted database backend requires `CRM_CREDENTIAL_ENCRYPTION_KEY`; production should source that key or a Vault/cloud secret-manager backend from protected runtime secret configuration. Access tokens, refresh tokens, client secrets and API keys must never be exposed in frontend responses or logs.

## Features

- Agent creation and management with instructions, identity, tone, model, citation, rate-limit, retention, and widget controls.
- Knowledge ingestion for files, URLs, sitemaps, and plain text, with `halfvec` dense search, PostgreSQL full-text search, reciprocal-rank fusion, and source citations.
- Grounded-before-stream chat over server-sent events, bounded conversation history, sensitive-data redaction, status changes, sentiment, and escalation workflows.
- Customizable website widget with origin checks, first-party hosted page, branding, placement, privacy, language and greeting controls.
- Operational dashboard, conversation analytics, knowledge health, lead management, and integration management.
- Meta WhatsApp Cloud API integration with Embedded Signup v4, encrypted customer tokens, signed/idempotent webhooks, and queued AI/human replies.
- Tenant-scoped authentication/authorization with short-lived access tokens, production HttpOnly refresh cookies, and Redis-backed one-time refresh-token families.
- Durable background work through RabbitMQ/Celery, replayable domain events through Kafka, and Redis-backed coordination.
- Transactional outbox delivery so committed database state and emitted domain events do not silently diverge.
- Structured logs, Prometheus metrics, liveness/readiness probes, CI checks, and container health gates.
- In-progress provider-neutral omnichannel Lead + CRM integration architecture described above, with tested ACK-preserving delivery and verification hardening.

## Repository map

Frontend, backend, databases, scripts, Docker guidance, and Kubernetes resources have explicit top-level boundaries. Start with [the repository structure guide](docs/repository-structure.md).

```text
frontend/              React + TypeScript administration UI and widget preview
backend/               FastAPI API, persistence, model/RAG services, integrations and workers
database/              PostgreSQL initialization and versioned database assets
infrastructure/        Redis, RabbitMQ, Kafka, and MinIO service boundaries
docker/                Docker operator documentation
kubernetes/            Kubernetes workloads and Kustomize configuration
scripts/               Local smoke and verification scripts
docs/                  Architecture, API, security, integration and operational guidance
.github/                CI and dependency-update automation
compose.yaml            Complete local service topology
```

## Quick start

### Windows: one click

Double-click `start.bat` in the repository root. It starts Docker Desktop when needed, checks the configured ports, builds the current backend/frontend using Docker's cache, runs migrations and services, checks readiness, and automatically starts ngrok. It opens the public app when the tunnel is ready, or the local app when ngrok is unavailable. Existing project containers and persistent data are reused. Closing the launcher window after startup leaves the services running.

The launcher prefers `.env.launch` when present (the verified local stack), otherwise `.env`, creating it from `.env.example` when necessary. An explicit `-EnvFile` or `NORTHSTAR_ENV_FILE` overrides that choice. It uses `compose.yaml` and an optional `compose.override.yaml`; it does not depend on temporary files under `reports/`. Printed URLs come from the selected configuration, normally http://localhost:3100 and http://localhost:8100/docs.

Sign in with `SEED_ADMIN_EMAIL` / `SEED_ADMIN_PASSWORD` from the selected environment file. Credentials are not printed. All local/public app links, API docs, configured CRM callbacks, webhook templates and local service consoles are printed together and saved to `reports/startup/links.txt`. Startup diagnostics are saved to `reports/startup/latest.log`. An occupied port, failed build, failed migration, or unhealthy service produces a nonzero exit code and a diagnostic message. Missing ngrok authentication leaves the healthy local app running and prints the setup command. Configure ngrok once with `ngrok config add-authtoken YOUR_TOKEN` locally; see [ngrok setup](docs/NGROK.md).

Optional command-line usage:

```bat
start.bat -NoBuild
start.bat -EnvFile .env -NoBrowser -NoPause
start.bat -TimeoutSeconds 600
start.bat -NoNgrok
start.bat -NgrokDomain your-domain.ngrok-free.dev
```

`-NoBuild` reuses existing images; run without it after changing code. `-NoNgrok` skips starting a tunnel; stop an existing tunnel with `start-ngrok.bat -Stop`. `NORTHSTAR_NO_BROWSER` and `NORTHSTAR_NO_PAUSE` remain supported. To stop the verified stack while preserving containers and data, run `docker compose --env-file .env.launch stop` (substitute `.env` if that was selected).

To exercise a protected route in Swagger, call `POST /api/v1/auth/login`, copy `accessToken`, then use **Authorize**.

### Develop the current frontend against the running backend

Start the stack with `start.bat`, then copy `frontend/.env.example` to
`frontend/.env.local` and run `npm run dev`. The example connects Vite's `/api`
proxy to the Docker API on port 8100. Set `VITE_DEV_API_URL=http://localhost:8000`
instead if you run the API directly on port 8000. Vite prints its frontend URL.

Demo mode is opt-in with `VITE_DEMO_MODE=true`; normal development and public
builds use the real backend. Saved demo sessions require a real sign-in when
switching to backend mode. The public launcher serves the current Docker web
build and its API proxy, so run `start.bat` without `-NoBuild` after code changes.

The Compose stack runs WhatsApp in a dedicated `whatsapp-worker`, separate from
document ingestion. See [WhatsApp processing and recovery](docs/WHATSAPP_RELIABILITY_REPAIR.md)
for the queue subscriptions, time limits and verification results.

Prerequisites:

- Docker Engine with Docker Compose v2
- At least 8 GB memory available to Docker
- Optional host development: Node.js 22.12+, Python 3.12+, and `uv`

macOS/Linux:

```bash
make up
make smoke
```

PowerShell:

```powershell
Copy-Item .env.example .env
docker compose up --build --detach
./scripts/smoke.ps1
```

Before connecting real data, replace all placeholder secrets in `.env` and supply a rotated `NVIDIA_API_KEY` when live model responses are required.

Local endpoints:

| Service | URL | Notes |
| --- | --- | --- |
| Web application | http://localhost:3100 | Nginx serves SPA and proxies `/api/*` |
| API | http://localhost:8100 | Direct API access |
| OpenAPI UI | http://localhost:8100/docs | Non-production interactive schema |
| Metrics | http://localhost:8100/metrics | Prometheus exposition |
| RabbitMQ management | http://localhost:15673 | Local management UI |
| MinIO console | http://localhost:9011 | Local object-store console |

All host-published ports bind to `127.0.0.1` by default. Change bind variables only when host firewall and authentication posture are understood.

## NVIDIA model configuration

Repository defaults support:

```dotenv
NVIDIA_MODEL=nvidia/nemotron-3-ultra-550b-a55b
NVIDIA_TEMPERATURE=1
NVIDIA_TOP_P=0.95
NVIDIA_MAX_TOKENS=16384
NVIDIA_ENABLE_THINKING=true
```

Thinking content is handled server-side and hidden chain-of-thought is never exposed. Accuracy depends primarily on clean approved sources, tenant-safe retrieval, citation requirements, abstention behavior, and evaluation rather than temperature alone.

Useful variables include `RETRIEVAL_CANDIDATE_LIMIT`, `RETRIEVAL_CONTEXT_LIMIT`, `RETRIEVAL_MIN_SCORE`, `REQUIRE_NVIDIA`, and `ALLOW_DETERMINISTIC_EMBEDDINGS`.

## WhatsApp Business connection

The Integrations page launches Meta Embedded Signup v4. A workspace owner chooses or verifies a WhatsApp Cloud API number, selects an active Northstar agent, and supplies the required two-step-verification PIN. Northstar exchanges the authorization code server-side, validates the WABA/number, registers the number, subscribes webhooks, encrypts the customer token, and routes messages through durable workers.

Production Meta callbacks require HTTPS:

```text
https://YOUR_DOMAIN/api/v1/webhooks/whatsapp
```

Never place the Meta App Secret, verification token, token-encryption key, customer token, or registration PIN in a `VITE_*` variable. See [docs/whatsapp.md](docs/whatsapp.md).

## Demo and live behavior

- Production/Docker builds use `VITE_DEMO_MODE=false`; API failures are not silently replaced with local browser data.
- Frontend-only development may use `VITE_DEMO_MODE=true` for seeded browser demos.

Production browser login keeps only the short-lived access-token/user session in browser storage; refresh credentials use secure HttpOnly cookie behavior defined by the backend deployment configuration.

## Stack and message semantics

| Component | Responsibility | Durability contract |
| --- | --- | --- |
| PostgreSQL + pgvector | Tenant data, leads, CRM delivery state, conversations, knowledge, outbox, projections | System of record; backed up and migrated |
| MinIO | Uploaded knowledge objects | Private/versioned storage |
| Redis | Rate limits, security/session coordination, integration coordination | Persistent/no-eviction for security-critical keys; not business-record storage |
| RabbitMQ + Celery | Work queues such as ingestion and WhatsApp jobs | At-least-once; handlers must be idempotent |
| Kafka | Ordered/replayable domain events including lead/CRM routing events | At-least-once; consumers deduplicate event IDs |
| Outbox relay | Publishes committed DB events to Kafka | Retries unpublished rows; duplicates possible |
| CRM router consumer | Converts lead sync events into durable CRM deliveries | Event-idempotent; DB delivery idempotency enforced |
| CRM delivery worker | Executes provider connector writes and persists ACK/attempts | Write retry is separate from acknowledged-delivery verification |
| CRM reconciliation | Recovers stale processing and retries read-back | GET failure must not resend an acknowledged write |
| Channel/CRM webhook consumers | Process persisted inbound integration events | Deployment wired; full provider/conflict/replay acceptance remains |
| Analytics consumer | Builds analytics projections | Replayable/idempotent |

RabbitMQ and Kafka are intentionally different: RabbitMQ carries work intended for a worker, while Kafka retains domain facts for replay by multiple consumers. Redis is coordination/security state, not the source of truth for leads or CRM delivery.

## Development

Install dependencies:

```bash
make bootstrap
```

Run frontend/API separately:

```bash
npm run dev
npm run api:dev
```

Quality checks:

```bash
make lint
make typecheck
make test
make build
docker compose config --quiet
```

Common operations:

```bash
make ps
make logs
make migrate
make down
make clean
make reset-data
```

## Documentation

- [Architecture and event flows](docs/architecture.md)
- [HTTP and streaming API](docs/api.md)
- [Security model and production checklist](docs/security.md)
- [Operations and recovery](docs/operations.md)
- [Meta WhatsApp setup and operations](docs/whatsapp.md)
- [Lead/CRM implementation status](docs/lead-crm-implementation-status.md)
- [CRM delivery verification and recovery](docs/operations/crm-delivery-verification.md)
- [Lead/CRM non-negotiables](docs/architecture/LEAD_CRM_NON_NEGOTIABLES.md)

## Production expectations

Before production use, replace single-node data services with durable monitored deployments; require TLS and authenticated broker connections; configure PostgreSQL point-in-time recovery; configure object-store lifecycle/backups; run multiple API/worker replicas; disable local fallbacks/environment seeding; use protected secret management; and place web/API behind trusted TLS ingress.

For the Lead/CRM subsystem specifically, do not activate a connection until authentication, API health, required schema/mapping validation, a test delivery and—where supported—read-back verification succeed. Keep queue/DLQ, token-refresh, provider latency, rate limits, schema drift and last-success/last-failure health visible in operations. Satisfy the open items in the implementation tracker before declaring the module complete or production-ready.

Pin images by digest and promote tested artifacts rather than rebuilding mutable branches. CI validates source/container builds when configured for the branch/PR, but provider credential validation, backup verification, model evaluation, and release approval remain explicit gates.
