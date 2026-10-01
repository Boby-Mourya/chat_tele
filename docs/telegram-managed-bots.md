# Managed Telegram connections

## One-time platform setup

Create a platform-owned manager bot in Telegram and enable **Bot Management Mode**
in the @BotFather Mini App. This external Telegram action cannot be performed by
the application. Configure these backend environment variables:

| Variable | Value |
| --- | --- |
| `TELEGRAM_MANAGER_BOT_TOKEN` | Manager bot credential, from your secret manager |
| `TELEGRAM_MANAGER_BOT_USERNAME` | Manager's actual username, without `@` |
| `TELEGRAM_MANAGER_WEBHOOK_SECRET` | A dedicated random value, at least 32 URL-safe characters |
| `TELEGRAM_PUBLIC_BASE_URL` | Public HTTPS API origin, e.g. `https://api.example.com` |
| `CRM_CREDENTIAL_ENCRYPTION_KEY` | Existing durable credential encryption key |

Generate the manager webhook secret using `secrets.token_urlsafe(32)` in Python.
For this Windows checkout, after putting the manager token in `.env` and enabling
Bot Management Mode, run the following to validate the bot and discover its username:

```powershell
backend/.venv/Scripts/python.exe scripts/configure-telegram-manager.py
docker compose up -d --no-build --wait --wait-timeout 180
docker compose exec api python -m northstar_api.services.telegram_manager_setup
```

The helper also creates the dedicated secret when missing. It never displays the
token. Set `TELEGRAM_PUBLIC_BASE_URL` to the current public HTTPS origin. In local
Compose, the API checks ngrok's local agent API at `host.docker.internal:4040`
when Connect is clicked and refreshes the manager webhook plus managed bot
webhooks in that workspace. `TELEGRAM_NGROK_TUNNEL_PORT` identifies the local
web tunnel (default 3100). Set `TELEGRAM_NGROK_API_URL` empty to disable discovery
and use the static origin instead. The Windows launcher also writes the current
tunnel origin to `TELEGRAM_PUBLIC_BASE_URL`.

Keep it in your deployment secret store. Never use a student's webhook secret.
The public origin must have no path, query, credentials, or fragment. For local
development, explicitly configure the HTTPS origin of the existing ngrok or
Cloudflare tunnel to the API. Restart services after changing environment values.

Apply migration `0069_telegram_managed_bots`, then register and verify the manager
webhook once using:

```sh
docker compose exec api python -m northstar_api.services.telegram_manager_setup
```

Run this to validate manager identity and management capability or when changing
the manager secret. It never prints credentials. Connect reconciles the manager
webhook and healthy managed bot webhooks in the current workspace. Reconnecting a
disconnected managed bot reuses its retained bot ID and retrieves its token again;
bot creation is not repeated while the manager still has access.
After changing the public origin, reconnect customer bots to move their webhooks.

## Customer experience

Create an agent assigned to Telegram. In Integrations, select Telegram and the
agent, then **Connect**. Allow the Telegram popup. In Telegram, create the managed
bot and confirm its attachment to the named agent. The application discovers the
actual bot name and username, registers its webhook, verifies it, and displays
Connected plus the student link. Closing the modal does not cancel the session;
Connect resumes it for the same administrator until its ten-minute expiry.

The manager message contains a visible **Create bot** button and a plain creation
link; opening a hidden reply keyboard is unnecessary. The app shows the current
setup step and an **Open Telegram again** link, including when popups are blocked.
Open the creation link in a current Telegram mobile or desktop client if your web
client does not support it. After creating the bot, return to the manager chat and
press **Connect to your agent**. Previously sent messages keep their old keyboard;
click Connect in the app and press Start again to receive the new message.

**Disconnect** removes the Telegram webhook and encrypted credentials, and disables
inbound delivery. It does not delete the user's bot. Connect reuses the retained
managed bot when Telegram still permits management. If ownership is gone, it opens
the creation flow. Transient failures retain state so Connect can retry safely.

## Multiple Telegram accounts

Select an agent, then use **Add account** to connect another Telegram bot without
disconnecting existing bots. Before pressing Start in Telegram, switch to the
Telegram account that should own the new bot. Telegram account switching happens
in Telegram itself; this application does not collect Telegram login credentials.

Use **Bot account** to select an existing bot and view its student link or disconnect
it individually. Reconnect targets that selected bot. Each new account has an
independent provisioning session; retrying the same attempt does not duplicate it.
Different tenants use their own authenticated workspaces and cannot access one
another's sessions, bots, or credentials. This feature adds bot connections, not
tenant memberships or cross-tenant access.

Migration `0070_telegram_multiple_accounts` removes the one-session-per-agent limit
and retains unique bot and connection ownership. Existing connections are preserved.
Start accepts either `accountId` (a new opaque UUID, reused for retries) or
`connectionId` (a scoped existing connection), alongside `agentId`.

## Student access

Copy the automatically discovered student link from Integrations or Deploy. Send
it to enrolled students. Students open the bot, press Start, and share their own
phone number once. Existing self-contact checks and active course/batch/agent
enrollment authorization remain required for course Q&A. Staff phone confirmation
is not a substitute for linking the actual Telegram account.

## Architecture and correlation

The platform manager webhook is `/api/v1/webhooks/telegram/manager`; customer bot
messages still use the existing channel webhook, raw-event/outbox, consumer,
education authorization, and outbound-delivery workers. No student messages are
processed by the manager handler.

`POST /api/v1/channels/telegram/connect/start` accepts only `agentId`.
`GET /api/v1/channels/telegram/provisioning/{sessionId}` returns safe status and bot
metadata. Existing `DELETE /api/v1/channels/connections/{id}` handles disconnect.
Sessions are scoped to tenant, workspace, agent, and initiating app user. Opaque
nonces are hashed for lookup and encrypted for resumption. Sessions expire and
Telegram updates are deduplicated. Agent permission and plan are rechecked before
completion. Bot IDs are uniquely claimed; duplicate updates cannot create another
connection. Secrets use the existing encrypted credential store.

Telegram's current `ManagedBotUpdated` and `ManagedBotCreated` objects **do not
echo the request_id** from `KeyboardButtonRequestManagedBot`. Therefore automatic
assignment to the last pending session is unsafe. This implementation sends a
signed, expiring Telegram confirmation for the specific bot-and-agent pairing to
the Telegram owner. It validates the sender, session, nonce generation, and unique
bot claim before attaching. Multiple tabs remain separate. This extra confirmation
is inside Telegram; the application still has only Connect/Disconnect actions.

Reference: [Telegram Bot API managed bots](https://core.telegram.org/bots/api#keyboardbuttonrequestmanagedbot),
[creation event](https://core.telegram.org/bots/api#managedbotcreated),
[token retrieval](https://core.telegram.org/bots/api#getmanagedbottoken).

## Legacy compatibility

Existing manually configured bot credentials and webhook verification continue
to work. No migration turns legacy bots into managed bots. The normal modal never
renders their secrets or manual setup instructions. Operational credential edits
remain available through the existing authenticated channel API for legacy bots
only; managed metadata cannot be supplied through that API. Disconnect a legacy
connection before provisioning its replacement.

## Validation and operations

Tests mock Telegram; no real bot tokens or student records are needed. The live
Telegram acceptance test requires the platform manager settings and external
BotFather management mode. Connection health checks identity and webhook URL;
inbound activity remains separate. A transient deleteWebhook failure retains
credentials for a safe retry rather than reporting a successful disconnect.

Management deduplication records contain only update IDs and timestamps; archive
old records according to the deployment's retention policy. HTTP client URL logging
is suppressed and provider error descriptions are not propagated, since they may
contain secrets. Audit logs include internal provisioning/connection IDs only.
