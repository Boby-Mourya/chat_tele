---
slug: agent-status-active-draft-training-and-error
title: 'Agent status: active, draft, training and error'
summary: Configure and operate Northstar AI agents using the current agent workspace.
category: agents
roles:
- owner
- admin
- member
- analyst
keywords:
- agent
- status
- active
- draft
- training
- and
- error
- chatbot
featured: false
sort_order: 210
---

# Agent status: active, draft, training and error

The status badge on **Agents** summarizes whether an agent is ready for use.

## Status meanings

- **active** — the agent is enabled for normal use.
- **draft** — configuration exists but the agent is not yet treated as active.
- **training** — background knowledge/configuration work is still in progress.
- **error** — the agent needs attention before normal use.

## What to do

Open the agent and check **Knowledge** for failed/processing sources, then review **Settings** and deployment configuration. If the issue is provider- or integration-specific, use the relevant troubleshooting guide.

## Important

A knowledge source has its own status. An active agent can still have an individual source that is processing or failed, so check both levels when troubleshooting.
