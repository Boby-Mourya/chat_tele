---
slug: configure-agent-security
title: Configure agent security
summary: Configure and operate Northstar AI agents using the current agent workspace.
category: agents
roles:
- owner
- admin
keywords:
- configure
- agent
- security
- chatbot
featured: false
sort_order: 200
---

# Configure agent security

Agent security settings protect availability, privacy, and deployment access.

## Before you start

Workspace **Owner** or **Admin** access is required.

## Steps

1. Open the agent's **Settings**.
2. Configure **Rate limiting**. Use a per-visitor limit for public traffic when appropriate.
3. Under **Privacy & handoff**, review **Email transcripts** and **Mask sensitive data**.
4. Use **Allowed domains** for Website deployments that should load only on approved domains.
5. Configure consent/privacy options from the Deploy privacy controls when required.
6. Save and retest the deployment.

## What happens next

Security checks are enforced by the backend/widget path; hiding controls in the UI is not the security boundary.

## Troubleshooting

If a legitimate site is blocked, verify its host against the exact Allowed domains list rather than disabling protection globally.
