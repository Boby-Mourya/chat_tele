---
slug: protect-meta-and-integration-credentials
title: Protect Meta and integration credentials
summary: Use this security/privacy control without weakening existing protections.
category: security
roles:
- owner
- admin
- member
- analyst
keywords:
- protect
- meta
- and
- integration
- credentials
- privacy
- security
featured: false
sort_order: 780
---

# Protect Meta and integration credentials

Integration credentials are secrets and must stay out of client-visible or searchable content.

## Before you start

This guide is available to all authenticated workspace roles.

## Rules

- Use the official **Integrations** flow for WhatsApp/Meta authorization.
- Keep Meta access tokens, two-step PINs, API keys, refresh tokens, and passwords out of agent instructions.
- Do not upload secrets as Knowledge sources.
- Do not include secrets in Help feedback/support requests or diagnostic metadata.
- Store server-side credentials only in the intended secure configuration/secret store.

## Troubleshooting

If a credential was accidentally exposed, rotate/revoke it at the provider and remove it from every system where it was stored. Do not paste the secret into a support ticket as evidence.
