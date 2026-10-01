---
slug: rate-limits
title: Rate limits
summary: Use this security/privacy control without weakening existing protections.
category: security
roles:
- owner
- admin
keywords:
- rate
- limits
- privacy
- security
featured: false
sort_order: 750
---

# Rate limits

Rate limiting protects public agents from abusive or automated traffic and helps control inference usage.

## Before you start

Workspace **Owner** or **Admin** access is required.

## Steps

1. Open the agent's **Settings**.
2. Find **Rate limiting**.
3. Choose **No limit** only for private/trusted deployments where that is appropriate.
4. For public traffic, choose **Per-visitor limit** and set **Messages per minute**.
5. Save and test normal usage.

## Troubleshooting

If legitimate users are throttled, adjust the configured limit carefully rather than disabling all protection. Help AI also has its own backend rate limit so support remains bounded.
