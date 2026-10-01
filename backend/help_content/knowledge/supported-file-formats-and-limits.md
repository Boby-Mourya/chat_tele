---
slug: supported-file-formats-and-limits
title: Supported file formats and limits
summary: Use trusted sources and understand how Northstar retrieves grounded information.
category: knowledge
roles:
- owner
- admin
- member
- analyst
keywords:
- supported
- file
- formats
- and
- limits
- rag
- source
- retrieval
featured: false
sort_order: 270
---

# Supported file formats and limits

The current knowledge upload flow supports a small, explicit set of document types.

## Supported uploads

- **PDF** (`.pdf`)
- **Microsoft Word DOCX** (`.docx`)
- **Plain text** (`.txt`)
- **Markdown** (`.md` or `.markdown`)
- **PNG image** (`.png`)
- **JPEG image** (`.jpg` or `.jpeg`)
- **TIFF image** (`.tif` or `.tiff`)

## Important limits

- Maximum uploaded file size: **500 MB** by default.
- Maximum PDF pages: **500** by default.
- Maximum extracted text: **2,000,000 characters** by default.
- Maximum generated chunks per source: **2,000** by default.
- Maximum uncompressed DOCX content: **100 MB** by default.

These backend values are configurable within guarded ranges, so a specific deployment can intentionally use different limits.

File uploads produce a draft extraction. Review each source page or image frame against its evidence before the source becomes searchable. A failed visual reading blocks verified release, and DOCX remains a draft until a rendered page derivative is available.

## Troubleshooting

If an accepted extension is rejected, make sure the file's declared content type matches the filename and the file is not larger than the configured limit.
