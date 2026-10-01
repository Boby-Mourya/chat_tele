---
slug: add-a-url
title: Add a URL
summary: Use trusted sources and understand how Northstar retrieves grounded information.
category: knowledge
roles:
- owner
- admin
keywords:
- add
- url
- rag
- source
- retrieval
featured: false
sort_order: 250
---

# Add a URL

A **Web page** knowledge source securely fetches a public page and indexes the extracted text.

## Before you start

Workspace **Owner** or **Admin** access is required.

## Steps

1. Open **Knowledge → Add source**.
2. Choose **Web page**.
3. Optionally add a source name.
4. Enter a complete **Page URL** such as `https://example.com/docs`.
5. Select **Add source**.
6. Wait for the page to be fetched, processed, and marked **ready**.

## Security

The backend uses a safe-fetch path and does not treat arbitrary internal/private network URLs as normal knowledge sources.

## Troubleshooting

If fetching fails, confirm the page is publicly reachable, returns supported web content, and does not require an authenticated browser session.
