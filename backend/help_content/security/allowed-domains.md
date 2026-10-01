---
slug: allowed-domains
title: Allowed domains
summary: Use this security/privacy control without weakening existing protections.
category: security
roles:
- owner
- admin
keywords:
- allowed
- domains
- privacy
- security
featured: false
sort_order: 740
---

# Allowed domains

Allowed domains limit which websites can load a published Website widget.

## Before you start

Workspace **Owner** or **Admin** access is required.

## Steps

1. Open the agent's deployment/security controls.
2. Add only trusted site hostnames.
3. Save.
4. Open **Deploy → Instant embed** and verify the domain list.
5. Test the actual production/staging domain.

## Security benefit

A copied public widget snippet should not automatically work from an unrelated website when domain protection is configured correctly.

## Troubleshooting

If a legitimate subdomain is rejected, compare the actual browser hostname with the configured parent/domain entry and update the allowlist deliberately.
