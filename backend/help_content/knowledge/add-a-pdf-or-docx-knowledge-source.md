---
slug: add-a-pdf-or-docx-knowledge-source
title: Add a PDF or DOCX knowledge source
summary: Use trusted sources and understand how Northstar retrieves grounded information.
category: knowledge
roles:
- owner
- admin
keywords:
- add
- pdf
- docx
- knowledge
- source
- rag
- retrieval
featured: false
sort_order: 230
---

# Add a PDF or DOCX knowledge source

Upload a document so Northstar can extract it for review before its approved text is indexed for the selected agent.

## Before you start

Workspace **Owner** or **Admin** access is required.

## Steps

1. Open the agent's **Knowledge** tab.
2. Select **Add source** and keep **File upload** selected.
3. Drop a PDF or DOCX into the upload area, or click to browse.
4. Confirm the file is **500 MB or smaller**.
5. Select **Add source**.
6. Wait for **Needs review**, open the page evidence, and compare the native and visual readings.
7. Approve each page. Indexing starts only after the required review is complete.

PDF, DOCX, TXT, Markdown, PNG, JPEG, and TIFF are accepted by the upload flow. DOCX approval is blocked until a rendered page derivative is available. The backend also limits page counts and extracted content to protect the ingestion service.

## Troubleshooting

If a DOCX contains unusually large embedded media or a PDF is extremely long, the backend may reject it even when the compressed upload is under 500 MB.
