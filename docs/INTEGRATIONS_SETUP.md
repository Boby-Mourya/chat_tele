# Integration catalogue

`/integrations` is the customer entry point. The catalogue groups CRM platforms first, then customer channels and developer tools. Search and category filters operate on the same catalogue. `/integrations/advanced` holds CRM mapping/routing, health history, delivery issues and channel health.

## Connection flows

- Zoho, Salesforce, HubSpot, Dynamics 365 and Pipedrive use OAuth. A configured platform app can supply the credentials; otherwise the customer enters their OAuth client ID and secret. The API supplies the exact redirect URL. The browser accepts completion only from the expected callback origin and popup. OAuth authorization prepares mapping and enables workspace lead sync; customers can review these settings afterward. No certification lead is automatically created by the catalogue.
- Freshsales uses an account URL and API key. Custom CRM API uses its base URL, authentication settings and lead endpoints. These run the existing health and provisioning checks.
- Slack, Telegram, Instagram and Facebook Messenger request provider credentials and a compatible agent. Credentials are encrypted, then checked against the provider. Corrections update the same connection and preserve its webhook URL. Credential validation alone does not claim incoming messages work: the catalogue shows **Finish webhook setup** until an event has arrived.
- WhatsApp uses the existing WhatsApp signup dialog. Website widget opens Deploy.

Saved credentials never appear in connection responses. Disconnecting removes credentials. OAuth app rotation discards tokens belonging to the previous client. Existing workspace isolation and billing restrictions remain enforced. Starter permits website/API channels but does not include CRM or messaging channels. Account fields remain editable; the API validates access on submission, and errors appear beside the authorization button.

## Verification

Focused frontend checks cover filtering, required fields, failed credentials, retry reuse, secret clearing, trusted OAuth callbacks, read-only access, plan access and CRM management. Backend checks cover encrypted OAuth credentials, rotation, workspace isolation, safe channel updates and the HTTP OAuth start contract (with a test OAuth state store).

Browser checks cover 1440, 1024, 768, 390 and 360 pixel widths, provider dialogs and the management route. Local screenshots are in ignored `reports/integrations-*.png`. Real provider authorization, incoming message delivery and CRM sync still require customer credentials, applicable plan access, and a public HTTPS endpoint for webhooks.
