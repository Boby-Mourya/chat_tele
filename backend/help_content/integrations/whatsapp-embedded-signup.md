---
slug: whatsapp-embedded-signup
title: WhatsApp Embedded Signup
summary: Understand and manage this integration behavior in the current workspace.
category: integrations
roles:
- owner
- admin
keywords:
- whatsapp
- embedded
- signup
- owner
- admin
- only
- channel
- connection
featured: false
sort_order: 470
---

# WhatsApp Embedded Signup

Northstar's WhatsApp integration uses Meta's embedded onboarding flow so an Owner/Admin can connect a WhatsApp Business setup without exposing credentials in the frontend.

## Before you start

Workspace **Owner** or **Admin** access is required.

## Steps

1. Open **Integrations**.
2. Find **WhatsApp** and select **Connect** or **Manage**.
3. Start the Embedded Signup flow in the WhatsApp modal.
4. Complete the Meta authorization/business selection steps shown by Meta.
5. Return to Northstar and verify the integration shows **Connected**.
6. Select the agent/channel assignment where required.

## Security

Provider tokens are handled server-side. Do not paste Meta access tokens into Help forms, agent instructions, or browser-visible fields.

## Troubleshooting

If the flow closes without connecting, reopen Integrations and check the connection status before repeating authorization.
