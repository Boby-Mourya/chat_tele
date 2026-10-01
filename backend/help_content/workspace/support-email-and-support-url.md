---
slug: support-email-and-support-url
title: Support email and support URL
summary: Understand this workspace setting, access rule, or management workflow.
category: workspace
roles:
- owner
- admin
keywords:
- support
- email
- and
- url
- owner
- admin
- only
- workspace
- team
featured: false
sort_order: 710
---

# Support email and support URL

White-label support settings control where the Help Center directs human-support requests for a workspace.

## Before you start

Workspace **Owner** or **Admin** access is required.

## Resolution order

1. If `whiteLabel.supportEmail` is configured, Help uses that address.
2. Otherwise Help falls back to **support@northstar.ai**.
3. If `whiteLabel.supportUrl` is configured, Help shows it as an optional external support resource; it does not replace the internal Help Center.

## Steps

Update the support fields in the White Label settings, save, then reopen **Help** and confirm the **Still need help?** panel displays the correct destination.

## Troubleshooting

Historical support requests keep the destination captured when they were submitted, so changing the setting does not rewrite older records.
