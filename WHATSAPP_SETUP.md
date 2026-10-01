# WhatsApp connection and messaging

Reference: [Meta's Business Messaging Sample Tech Provider App](https://github.com/fbsamples/business-messaging-sample-tech-provider-app).

## Configure the deployment

### Add your own accounts in the app

Open **Integrations > WhatsApp > Add account**. Enter an account name, Meta App ID, App secret, WhatsApp Business Account ID, system-user access token, and a webhook verification secret of at least 32 characters. Northstar verifies the app/token permissions and WABA access before saving encrypted credentials. This path does not require the deployment owner's Embedded Signup configuration. The server still needs `CRM_CREDENTIAL_ENCRYPTION_KEY` to protect saved secrets.

Each account has its own generated callback URL. After ngrok is online, configure your Meta app's WhatsApp `messages` webhook subscription and use **Activate / refresh webhook**. Northstar installs a WABA-specific callback so different business accounts stay isolated.

Use **Update account credentials** to replace an expiring token or rotated secrets. Replacement credentials are verified before saving, never revealed back to the browser, and require webhook activation again. Other business accounts remain unchanged.

Select an account, choose a phone number discovered from Meta, enter its six-digit registration PIN, and click **Register number**. Repeat for additional numbers or add another account. Phone numbers must first be added and verified in Meta WhatsApp Manager; the application does not bypass Meta's phone verification.

When creating a bot, select **WhatsApp** in the Channel step, then choose an available connected number. The number is assigned in the same transaction as creation and appears on the bot card. Numbers assigned to other bots cannot be taken during creation. Education bots reserve their number while in draft and do not process WhatsApp messages until published. The workspace plan must allow WhatsApp; the creation form displays the server?s reason if access is denied.

In **Deploy**, select a published bot and the **WhatsApp** channel. Choose a saved number and click **Apply number assignment**. Each number serves one bot, and each bot has one assigned number. Other saved numbers remain available. Switching numbers closes affected old threads and cancels pending replies before new messages use the new assignment. Selecting **No number assigned** releases the number without deleting its credentials. Unassigned numbers record incoming messages without running an AI bot.

The callback URL is generated and copyable; arbitrary edits would point Meta at an endpoint that does not exist. Account credential fields are editable during account creation.

### Platform Facebook Embedded Signup (optional)

In `.env.launch`, configure `META_APP_ID`, `META_APP_SECRET`, `META_WHATSAPP_CONFIGURATION_ID`, `META_WHATSAPP_WEBHOOK_VERIFY_TOKEN`, and `META_WHATSAPP_TOKEN_ENCRYPTION_KEY`. Use a strong random verification token and encryption key; preserve the encryption key across restarts so existing connections remain decryptable. Configure `NVIDIA_API_KEY` for model-generated replies. Do not put server secrets in frontend environment variables.

Create a Meta Business app with WhatsApp and Facebook Login for Business. Create an Embedded Signup configuration granting `whatsapp_business_management` and `whatsapp_business_messaging`. Configure your public HTTPS domain in the Meta app's allowed domains/login settings. Complete Meta verification, app review and advanced access requirements before onboarding other businesses; development-mode access is restricted by Meta.

Run `start.bat`. Ensure ngrok reports a verified public URL. In Meta's WhatsApp webhook configuration, register the callback URL displayed in Integrations > WhatsApp. For the configured domain it is:

`https://isolation-unaligned-catalog.ngrok-free.dev/api/v1/webhooks/whatsapp`

Use the value of `META_WHATSAPP_WEBHOOK_VERIFY_TOKEN` for verification and subscribe to the `messages` field. Keep Docker and ngrok running. A local callback cannot receive Meta events.

## Connect and verify

1. Publish the agent that should answer customers. Its instructions and knowledge determine replies.
2. Open Integrations > WhatsApp, select the agent, enter the six-digit number registration PIN, and choose Continue with Facebook.
3. In Meta, authorize your business, choose/create a WhatsApp Business Account, and select and verify its Cloud API phone number. Northstar exchanges the one-time code, validates permissions and number ownership, registers the number, subscribes the app, and encrypts the access token.
4. Use **Check with Meta** to validate the token and number. This check does not establish that a message reached a customer.
5. Use **Open WhatsApp**, or message the connected number from a separate customer phone. Confirm an incoming receipt appears in Message activity, an AI reply arrives, and provider delivery/read receipts appear. Meta test numbers require an allowed test recipient.
6. Open Conversations, filter WhatsApp, and select the customer thread. Incoming messages refresh every ten seconds. Send a teammate reply and check its delivery evidence under the integration.
7. After 24 hours without a customer message, free-form replies are rejected. Choose **Send WhatsApp template** in the conversation, select an approved text template, fill its header/body parameters, confirm customer opt-in, and queue it. Meta may charge for templates. The backend rechecks approval and stores the send durably; the worker can deliver it outside the service window.

## Troubleshooting and scope

- Missing server settings and the exact callback URL are shown before signup. The verification token and app secret are never returned to the browser.
- Activity distinguishes inbound processing from signed provider `sent`, `delivered`, `read`, and `failed` receipts. Queue acceptance is not delivery proof. Duplicate/out-of-order status callbacks retain each transition once.
- Invalid/expired authorization requires reconnection. Disconnect cancels pending work and closes affected threads; connect again to replace credentials.
- Inbound text, quick-reply buttons and interactive text selections are supported. Other incoming media is recorded as ignored; media download/transcription is not implemented.
- This composer supports approved text header/body templates with positional or named parameters. Media/button templates are listed with an explanation and cannot be queued here. Create/edit templates in Meta WhatsApp Manager.
- Standard Cloud API signup is supported. WhatsApp Business App Coexistence onboarding is a separate Meta flow and is not implemented.
- Live verification requires actual Meta configuration, a registered number, a reachable HTTPS webhook, and a customer test message. Automated tests mock Meta and model responses; they do not prove a live Meta connection.

## Verification

Backend tests: `backend/tests/test_whatsapp.py` and `backend/tests/test_whatsapp_templates.py`.
Frontend tests cover the Meta SDK, template consent/parameters/error handling, and WhatsApp workspace preview.
Migration `0039_whatsapp_delivery_receipts` adds tenant-isolated provider receipts and durable template payloads.


## Education enrollment through WhatsApp

1. In Education > Students, add or edit the student and enter **Student WhatsApp number** with the country code. This is the student's personal number, not the business number assigned to the bot.
2. Staff must confirm ownership before selecting the verification checkbox. Unconfirmed numbers remain pending and cannot access private course content. Changing the primary number revokes its previous primary identity and requires confirmation again.
3. Create an active course and batch with valid dates. Open the student's **Enrollments** and select the course, batch, and education bot; the selector shows the bot's assigned WhatsApp number. Activate the enrollment with appropriate access dates.
4. Publish the education bot after enrollment configuration and add course-scoped knowledge. Configure NVIDIA_API_KEY in .env.launch for model-backed answers.
5. Messages from the verified student number are checked against the bot, enrollment, course, batch, and access dates before education retrieval. Unknown or ineligible numbers receive an access-help reply without private course content.

CRM connections are configured separately in Integrations. A successful local test does not establish provider authorization: connect an actual CRM account, activate mapping/routing, and verify provider health before relying on live sync. Student enrollment alone does not automatically export the student as a sales lead.


## Website visitor details

Conversations > visitor panel > Edit visitor details saves contact details, page URL/slug,
referrer, IP, approximate location, time zone, language and UTM attribution. If a linked
lead exists, saving updates its contact and attribution fields and requests CRM sync.
Existing conversations cannot recover IP/UTM data that was never collected.

The website widget captures only the five standard UTM query parameters, removing other
query parameters and fragments. Websites may explicitly identify a known visitor through
`data-visitor-name`, `data-visitor-email`, and `data-visitor-phone` on the widget script.
An IP address does not identify a visitor's name, email, or phone.

Set `VISITOR_TRUSTED_PROXY_CIDRS` to the actual reverse-proxy network CIDRs. Only those
peers' forwarded chains are used, reading from right to left; never trust arbitrary
public clients. The API's authentication proxy behavior is unchanged. Update this setting
if Docker networks change. `VISITOR_GEOIP_ENABLED=true` enables a best-effort HTTPS
lookup at ipwho.is for public IPs only, with a two-second timeout. This sends the public
IP to that provider. Private IPs, provider limits, and lookup failures leave location
unavailable and do not prevent chat. Location is approximate and can be corrected manually.
