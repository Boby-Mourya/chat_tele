---
slug: preview-whatsapp-deployment
title: Preview WhatsApp deployment
summary: Assign a WhatsApp number and customize the bot’s welcome message and automatic reply structure.
category: deploy
roles:
- owner
- admin
- member
- analyst
keywords:
- preview
- whatsapp
- deployment
featured: false
sort_order: 590
---

# Preview WhatsApp deployment

WhatsApp bots have their own deployment settings. Website colors, fonts, widget size, launchers, browser greetings, and embed snippets are hidden when WhatsApp is selected.

## Before you start

Connect a number in **Integrations → WhatsApp**. You need permission to edit the selected bot. Education bots also require their course and enrollment setup before activation.

## Steps

1. Open **Deploy**, select your bot, and select **WhatsApp** as its deployment channel.
2. In **WhatsApp number**, assign a connected number. **Apply number assignment** saves that assignment separately.
3. Open **Welcome message** and enter the exact text to send when a customer says Hi, Hello, or another short greeting. Use the switch to enable or disable this response. The welcome is sent after an incoming message; it is not an unsolicited message.
4. Select text and use the formatting toolbar for bold, italic, strikethrough, monospace, lists, and quotes. WhatsApp controls the font family, size, colors, and interface.
5. Open **Message format** to arrange automatic answers. Include `{message}` exactly once for the answer; optionally use `{bot_name}`. Add a heading, spacing, or closing text. The welcome message has its own formatting.
6. Set **Response language** for generated answers. Write your custom welcome and closing text in the desired language.
7. Use **Bot activation** to switch between active and draft, then click **Apply**. Settings are saved per bot and used for subsequent replies.
8. Use **Get link** or **QR code** to share a WhatsApp chat link for the assigned number. These options do not create website embeds.

## What happens next

The preview shows message formatting as you edit. Saving does not send a customer message. Existing messages remain unchanged. Education access checks still run before welcome messages and answers are sent.

## Troubleshooting

If **Apply** is disabled, check that the enabled welcome is not empty and the reply structure contains `{message}` exactly once. A welcome can contain up to 4,096 characters; a reply structure can contain up to 1,500 characters. Long generated replies are split into messages for delivery. If activation fails, check the number assignment and education enrollment requirements. If sharing has no link, assign a connected number first.
