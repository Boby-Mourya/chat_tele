---
slug: sensitive-data-masking
title: Sensitive-data masking
summary: Use this security/privacy control without weakening existing protections.
category: security
roles:
- owner
- admin
keywords:
- sensitive
- data
- masking
- privacy
- security
featured: false
sort_order: 730
---

# Sensitive-data masking

Sensitive-data masking reduces the chance that common credentials, payment details, or government identifiers are retained in logs/operational data.

## Before you start

Workspace **Owner** or **Admin** access is required.

## Where to configure it

- Agent **Settings → Privacy & handoff → Mask sensitive data** for agent behavior.
- **Workspace → Security controls → Sensitive data masking** for workspace-wide protection exposed by the current UI.

## Good practice

Masking is a defense-in-depth control, not permission to intentionally collect secrets. Do not ask visitors to paste passwords, API keys, Meta tokens, or payment credentials.

## Troubleshooting

If a sensitive value appears where it should have been masked, stop using that data in tests and report the exact route/type of value without copying the secret itself.
