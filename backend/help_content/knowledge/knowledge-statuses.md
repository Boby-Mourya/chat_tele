---
slug: knowledge-statuses
title: Understand Processing, Ready, and Failed states
summary: Know what knowledge processing states mean.
category: knowledge
roles:
- owner
- admin
- member
- analyst
keywords:
- processing
- ready
- failed
- status
featured: true
sort_order: 30
---

# Understand knowledge processing states

- **Processing** means ingestion is still running.
- **Ready** means processing completed and the source is available to retrieval.
- **Failed** means ingestion could not finish.

If a source stays Processing unexpectedly, refresh and verify ingestion worker/infrastructure health. If it fails, review the visible error and correct or replace the source if your role permits it.
