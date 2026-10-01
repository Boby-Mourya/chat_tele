---
slug: delete-or-replace-a-knowledge-source
title: Delete or replace a knowledge source
summary: Use trusted sources and understand how Northstar retrieves grounded information.
category: knowledge
roles:
- owner
- admin
keywords:
- delete
- replace
- knowledge
- source
- owner
- admin
- only
- rag
- retrieval
featured: false
sort_order: 300
---

# Delete or replace a knowledge source

Use source replacement when an old document or page should no longer influence answers.

## Before you start

Workspace **Owner** or **Admin** access is required.

## Replace a source

1. Add the updated source first.
2. Wait until the new source is **ready**.
3. Test the important questions against the updated content.
4. Return to the Knowledge table and delete the obsolete source using its trash action.

## Why this order is safer

It reduces the period where the agent has no trusted version of the information.

## Troubleshooting

If deletion is rejected, confirm Owner/Admin access. If the old information still appears after replacement, confirm the old source was actually removed and retest in a new conversation.
