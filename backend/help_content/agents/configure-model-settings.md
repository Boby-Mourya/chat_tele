---
slug: configure-model-settings
title: Configure model settings
summary: Configure and operate Northstar AI agents using the current agent workspace.
category: agents
roles:
- owner
- admin
keywords:
- configure
- model
- settings
- agent
- chatbot
featured: false
sort_order: 180
---

# Configure model settings

Northstar's **LLM connection** settings control the NVIDIA generation behavior for an agent.

## Before you start

Workspace **Owner** or **Admin** access is required.

## Steps

1. Open the agent and select **Settings**.
2. In **LLM connection**, review the selected **Model**.
3. Adjust **Creativity** only when the use case needs more or less variation.
4. Turn **Reasoning mode** on when complex requests benefit from deeper reasoning.
5. Turn **Citations** on when answers should link back to connected sources when available.
6. Save and test a fixed set of questions before and after a change.

## What happens next

Model settings affect generation, but they do not replace good retrieval. If the answer lacks the right facts, improve Knowledge first.

## Troubleshooting

When the provider is unavailable, treat it as a model connectivity issue rather than changing unrelated agent settings.
