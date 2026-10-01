---
slug: developer-api-overview
title: Developer API overview
summary: Understand and manage this integration behavior in the current workspace.
category: integrations
roles:
- owner
- admin
- member
- analyst
keywords:
- developer
- api
- overview
- channel
- connection
featured: false
sort_order: 510
---

# Developer API overview

The Developer API lets a workspace build custom experiences around Northstar rather than using only the Website widget.

## Before you start

This guide is available to all authenticated workspace roles.

## Where to find details

- Agent **Embeddings & deployment** includes a REST API example for chat streaming.
- **Workspace → API keys** is where Owner/Admin users create and revoke server-side credentials.
- **Integrations** shows **Developer API** as an available developer integration.

## Security

Use API keys only from trusted server-side code. Never put a workspace secret key in public JavaScript, a Help request, or a client-side environment variable.

## Troubleshooting

If an API request returns authorization errors, verify the key has not been revoked and that the request uses the expected server-side authorization format.
