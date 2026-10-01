---
slug: configure-allowed-domains
title: Configure allowed domains
summary: Configure, preview, and validate this deployment behavior.
category: deploy
roles:
- owner
- admin
keywords:
- configure
- allowed
- domains
- deployment
- preview
featured: false
sort_order: 570
---

# Configure allowed domains

Allowed domains restrict which websites can load a published agent widget.

## Before you start

Workspace **Owner** or **Admin** access is required.

## Steps

1. Open the agent's deployment/security controls.
2. Add the exact hostnames that are allowed to load the widget.
3. Save the agent.
4. In **Deploy → Instant embed**, review the connected/allowed domain list.
5. Test from the real hostname.

Subdomains can be matched according to the backend/widget domain logic when the configured parent domain permits them.

## Troubleshooting

If Deploy reports that the current host is not allowed, add the correct host rather than disabling the domain check globally.
