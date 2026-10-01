---
slug: add-a-sitemap
title: Add a sitemap
summary: Use trusted sources and understand how Northstar retrieves grounded information.
category: knowledge
roles:
- owner
- admin
keywords:
- add
- sitemap
- rag
- source
- retrieval
featured: false
sort_order: 260
---

# Add a sitemap

Use **Sitemap** to ingest a controlled set of pages from an XML sitemap.

## Before you start

Workspace **Owner** or **Admin** access is required.

## Steps

1. Open **Knowledge → Add source**.
2. Choose **Sitemap**.
3. Enter the full **Sitemap URL**.
4. Select **Add source**.
5. Northstar reads page locations from that sitemap and securely fetches pages from the same sitemap host.
6. Monitor the source until it is **ready**.

The backend has a configurable sitemap URL limit (25 pages by default) to keep ingestion bounded.

## Troubleshooting

Use a valid XML sitemap and make sure its listed pages are public and on the expected host.
