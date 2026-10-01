# Managed Telegram implementation record

## Architecture

The new manager control plane creates or reuses existing ChannelConnection and
WorkspaceChannelConnection records. Customer messages continue through the existing
channel webhook, outbox, event consumer, education authorization and outbound worker.
Managed credentials and generated webhook secrets stay encrypted on the backend.
Connection health requires getMe and verified getWebhookInfo, not a first message.

## Source files added

- `backend/src/northstar_api/telegram_provisioning.py`: provisioning state and manager update deduplication models.
- `backend/src/northstar_api/services/telegram_provisioning.py`: validation, correlation, provisioning, retry, reconnect and disconnect.
- `backend/src/northstar_api/services/telegram_manager_setup.py`: one-time manager bootstrap command.
- `backend/src/northstar_api/routers/telegram_connect.py`: scoped start/status APIs and authenticated manager webhook.
- `backend/migrations/versions/0069_telegram_managed_bots.py`: new control-plane tables and runtime grants.
- `frontend/src/components/telegram-setup-modal.tsx`: Connect/Disconnect, polling and read-only actual bot identity/link.
- `backend/tests/test_telegram_managed.py`: managed lifecycle, security, failure and API-contract coverage.
- `frontend/src/components/telegram-setup-modal.test.tsx`: no-secret UI, lifecycle, URL validation and polling cleanup.
- `reports/verify-managed-telegram.py`: read-only live API/modal verification without credential output.

## Existing source files updated

- `backend/src/northstar_api/services/telegram.py`: centralized managed-token, webhook, callback and student-access calls; safe errors.
- `backend/src/northstar_api/config.py`: manager settings.
- `backend/src/northstar_api/routers/__init__.py`: route registration.
- `backend/src/northstar_api/routers/channels.py`: managed credential-edit protection, disconnect, inbound concurrency and health handling.
- `backend/src/northstar_api/lead_crm/channels.py`: public connection ID available to health checks.
- `backend/src/northstar_api/lead_crm/channel_providers.py`: Telegram identity and webhook validation.
- `backend/src/northstar_api/workers/channel_health_monitor.py`: public ID passed to connector.
- `backend/src/northstar_api/workers/telegram_tasks.py`: preserve disabled/managed health state during outbound completion.
- `backend/migrations/env.py`: provisioning model registration.
- `frontend/src/lib/lead-crm-api.ts`: typed Telegram start/status/disconnect APIs.
- `frontend/src/components/integration-setup-modal.tsx`: route Telegram to its managed modal inside the existing hub.
- `frontend/src/pages/IntegrationsHubPage.tsx`: healthy Telegram no longer requires inbound activity.
- `frontend/src/pages/DeployPage.tsx`: actual student bot link.
- `backend/tests/test_telegram_outbound.py`: webhook health mock added to existing health test.
- `backend/tests/test_channel_health_monitor.py`: deterministic fixture timestamp matching the test clock.
- `.env.example`, `compose.yaml`: backend-only manager configuration.
- `README.md`, `docs/telegram-student-enrollment.md`, `docs/telegram-managed-bots.md`: setup and usage documentation.

## Configuration and endpoints

New settings: `TELEGRAM_MANAGER_BOT_TOKEN`, `TELEGRAM_MANAGER_BOT_USERNAME`,
`TELEGRAM_MANAGER_WEBHOOK_SECRET`, `TELEGRAM_PUBLIC_BASE_URL`.
Existing `CRM_CREDENTIAL_ENCRYPTION_KEY` remains required.

New endpoints:

- `POST /api/v1/channels/telegram/connect/start` with `{ "agentId": "..." }`.
- `GET /api/v1/channels/telegram/provisioning/{sessionId}`.
- `POST /api/v1/webhooks/telegram/manager`, dedicated manager secret required.

Existing channel DELETE now removes Telegram's webhook before clearing credentials.
No bot deletion is performed. The student channel webhook path is unchanged.

## Validation commands

```powershell
backend/.venv/Scripts/python.exe -m pytest -c backend/pyproject.toml backend/tests/test_telegram_managed.py backend/tests/test_telegram_outbound.py backend/tests/test_telegram_phone_enrollment.py backend/tests/test_channel_health_monitor.py -q --tb=short --show-capture=no
backend/.venv/Scripts/python.exe -m pytest -c backend/pyproject.toml backend/tests/test_entitlements.py -q --tb=short --show-capture=no
npm run typecheck
npm run test --workspace @northstar/web -- src/components/telegram-setup-modal.test.tsx src/pages/IntegrationsHubPage.test.tsx src/pages/StudentsPage.test.tsx --testTimeout=15000 --maxWorkers=1
npm run build
docker compose up -d --no-build --wait --wait-timeout 180
backend/.venv/Scripts/python.exe reports/verify-managed-telegram.py
```

The education channel runtime and manual health snapshot regression tests were also
run. A combined entitlement run encountered shared test-data agent limits; the
entitlement suite passed independently. The initial student UI parallel run timed
out; the single-worker run passed. These are reported rather than hidden.

Verified local result on 2026-09-30: migration 0069 applied; API and web healthy;
channel event consumer and health monitor running; live managed endpoints present;
live Telegram modal has no credential inputs. The 38-test backend lifecycle/student/
health regression run passed; a subsequent 28-test managed/outbound run passed after
adding the client response-contract test. All 5 standalone entitlement tests and
14 frontend tests passed. TypeScript checking and the host production build passed.
The four manager settings were absent in the running API; no real Telegram creation
or student Q&A is claimed as verified until the external setup is completed.

## External setup and assumptions

The platform owner must create/configure a real manager bot, enable Bot Management
Mode in Telegram and run the manager bootstrap command. The code cannot manufacture
that external credential. Tests use synthetic credentials and mocked Telegram.

Telegram creation updates do not echo the keyboard request ID. The manager therefore
asks for signed confirmation of the exact agent-and-bot pairing inside Telegram.
This is deliberate protection for simultaneous tabs/workspaces. The application
still exposes only Connect/Disconnect plus agent selection and read-only links.

Student contact verification and active enrollment checks remain authoritative.
Managed bot access is enabled for students at the Telegram layer; that does not
grant access to protected course answers. Legacy bots keep their existing pipeline.

For this local deployment, Docker's container frontend build stalled. A host Vite
production build and the temporary `reports/compose-telegram-final.yaml` package the
compiled frontend into the existing nginx runtime. The normal Dockerfiles remain
available for clean installations; the report override assumes local base images
already exist and is not the setup path for another laptop.
