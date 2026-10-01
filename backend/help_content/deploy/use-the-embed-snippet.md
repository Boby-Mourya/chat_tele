---
slug: use-the-embed-snippet
title: Use the embed snippet
summary: Configure, preview, and validate this deployment behavior.
category: deploy
roles:
- owner
- admin
keywords:
- use
- the
- embed
- snippet
- deployment
- preview
featured: false
sort_order: 560
---

# Use the embed snippet

**Instant embed** installs the Website widget with a script tag tied to the selected agent's public identifier.

## Before you start

Workspace **Owner** or **Admin** access is required.

## Steps

1. Open **Deploy → Instant embed** for the intended agent.
2. Copy the generated snippet exactly.
3. Paste it before the closing `</body>` tag on each page where chat should appear.
4. Publish the website change.
5. Open the live page and verify the launcher appears.

## Security

The public agent identifier used by the widget is not a workspace API secret. Keep actual API keys out of the embed code.

## Troubleshooting

If the script loads but the widget is blocked, check **Allowed domains** and Content Security Policy settings.
