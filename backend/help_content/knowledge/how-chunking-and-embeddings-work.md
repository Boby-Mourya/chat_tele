---
slug: how-chunking-and-embeddings-work
title: How chunking and embeddings work
summary: Use trusted sources and understand how Northstar retrieves grounded information.
category: knowledge
roles:
- owner
- admin
- member
- analyst
keywords:
- how
- chunking
- and
- embeddings
- work
- rag
- source
- retrieval
featured: false
sort_order: 280
---

# How chunking and embeddings work

Northstar does not send an entire knowledge library to the model for every question. It converts processed source text into smaller retrievable units.

## Pipeline

1. A source is extracted into text.
2. The ingestion service splits the text into **chunks**.
3. NVIDIA embeddings (or the deterministic development/test path) convert chunks into vectors.
4. PostgreSQL/pgvector stores the chunk vectors alongside searchable text.
5. At question time, Northstar combines vector similarity with lexical/full-text matching.
6. Only the best grounded evidence is supplied to generation.

## Why this matters

Smaller focused chunks improve retrieval precision and keep prompts bounded. The Knowledge page shows the number of chunks produced for each source.

## Troubleshooting

If the right source exists but retrieval misses it, improve headings/content clarity or split very broad sources into focused documents.
