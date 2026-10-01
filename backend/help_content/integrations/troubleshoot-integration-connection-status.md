---
slug: troubleshoot-integration-connection-status
title: Troubleshoot integration connection status
summary: Understand and manage this integration behavior in the current workspace.
category: integrations
roles:
- owner
- admin
keywords:
- troubleshoot
- integration
- connection
- status
- channel
featured: false
sort_order: 530
---

# Troubleshoot integration connection status

Use the Integrations card and Deploy channel panel together to determine whether a channel is actually connected and usable.

## Before you start

Workspace **Owner** or **Admin** access is required.

## Steps

1. Open **Integrations** and locate the channel.
2. Check whether it shows **Connected**, **Connect**, **Admin only**, or **Coming soon**.
3. For WhatsApp, use **Manage** and verify the embedded connection details.
4. Open **Deploy** and select the same channel.
5. Confirm the Deploy panel also reports it as available/connected.
6. Refresh after changing the connection so stale client state is not mistaken for a backend failure.

## Troubleshooting

A **Coming soon** integration cannot be repaired by toggling client state. An **Admin only** state requires Owner/Admin access.
