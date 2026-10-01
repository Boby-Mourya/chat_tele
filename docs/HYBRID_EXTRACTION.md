# Hybrid source extraction

The workflow in [HYBRID_EXTRACTION_PLAN.md](HYBRID_EXTRACTION_PLAN.md) is implemented using the existing NVIDIA provider, native parsers, durable worker checkpoints, and a source-based review gate. It preserves source mistakes and never generates answers during extraction. Extraction is separate from the existing indexing pipeline; only a verified release can enter indexing.

## Processing and evidence

- PDF: pypdf native text and page labels; PyMuPDF text spans, word geometry, tables, images, annotations, form fields, rotation and page rendering. Every page receives an independent visual inventory and bounded region transcription.
- DOCX: ordered OOXML inventory, stable logical IDs, nested tables, merged-cell metadata, equations, numbering, relationships, text boxes, content controls, notes, comments, hidden content and revisions. Deleted and hidden content remain separately labeled. A field-frozen derivative is rendered with LibreOffice, recording version, fonts, locale and revision policy. External render dependencies, macros and embedded objects block rendering. Ambiguous logical-to-rendered mappings require review.
- Images: original bytes and every supported PNG/JPEG/TIFF frame are preserved, with EXIF orientation and resizing recorded. Captions, labels, annotations, observed relationships and derived descriptions occupy separate fields.
- Text/Markdown: strict UTF-8, or BOM-declared UTF-16/32, preserves exact characters, original bytes, line endings and line byte ranges. Unsupported encodings remain blocked with their original source available. Text has no invented physical pagination.

The archive contains the preserved original, `extracted.json`, readable `extracted_review.txt`, `validation_report.txt`, `correction_history.json`, page images, region crops, raw/parsed NVIDIA attempts, Word derivatives where available, and a SHA-256 manifest. TXT includes a readable projection and JSON-escaped canonical records; it is never rewritten by a model. Archive members and ZIP timestamps are ordered deterministically for the same record. Random capability challenges and human timestamps intentionally differ between runs.

PDF/image coordinates are explicitly identified as rendered pixels, with source dimensions, rotation, scale and transform IDs. Inventory coordinates remain in raw/parsed call evidence. Table cells have stable IDs, spans, states, header links, units and source table references. Physical fragments remain separate; reviewed continuation links assemble logical groups. Captions and printed answer keys require explicit source-based relationships.

## NVIDIA only

All vision calls use `langchain_nvidia_ai_endpoints.ChatNVIDIA` with `meta/llama-3.2-11b-vision-instruct`. Both reading and dispute review use this same NVIDIA model; repeat calls are not independent model corroboration. Existing NVIDIA chat and embedding selections are preserved. Provider/model overrides for vision are rejected.

Before reading a new visual source, a random value present only in image pixels probes actual image-reading capability. Failure blocks visual extraction. The independent inventory/transcription prompts never receive the native transcript. Raw responses, termination status, parse failures, prompt/model identity and image checksums are retained; reasoning is not source text.

Incomplete JSON or truncated completions trigger bounded crop subdivision. At most three additional calls per inventory/region recovery are allowed, with a separate per-page call and elapsed-time cap. Split boundaries require human review. Disputed regions may receive one expanded-context crop through the same NVIDIA model, when this supplies different source pixels. Competing candidates remain unresolved until source review; no majority vote or model confidence score approves a value.

## Review and release

The Knowledge screen opens a review panel with full-resolution page evidence, native/visual candidates, editable region text and structure, table-cell projections, related source IDs, issue decisions, checks and blockers. Reviewers can save one page at a time. Structured details include cell states/spans/header relationships, equations, question options/subparts, figure labels, captions and typed relationships. Blank source units need explicit confirmation.

Each save checks the current extraction revision, writes a new evidence archive and records reviewer, reason, source/image/content hashes and the before/after correction history. Updates are transactional; rejected reviews do not mutate the record. Content or relationship changes invalidate previous acceptance. Technical failures require reprocessing, and uncertain/incomplete regions cannot be approved.

Every source unit needs a source-based human review. Numerical, mathematical, table and question/answer content requires a second **different user** on the identical reviewed version. Ten explicit check groups cover source/render integrity, identity, coverage, text, tables/numbers, educational structure, visual audit, continuity, export consistency and human acceptance. Unresolved issues block release even when other checks pass. `NOT_MEASURED` remains the accuracy value without labeled ground truth.

The indexing worker independently verifies the archive, its checks, release status, revision and exact selected content. Uploading a file with supplied text cannot bypass review. Draft exports remain available while blocked, including when the model or Word renderer is unavailable.

## Deployment and recovery

Set `NVIDIA_API_KEY` in the deployment environment. No key is committed. The backend container installs LibreOffice Writer, fontconfig and DejaVu/Noto fonts. A host installation needs `soffice` on PATH, or an explicit `EXTRACTION_WORD_RENDERER`. Its recorded font environment determines Word pagination; inspect substituted fonts against the original presentation.

Relevant settings are documented in `backend/.env.example`:

| Setting | Default |
| --- | --- |
| `EXTRACTION_VISION_MAX_TOKENS` | 512 |
| `EXTRACTION_VISION_TIMEOUT_SECONDS` | 120 |
| `EXTRACTION_RENDER_DPI` | 300 |
| `EXTRACTION_MAX_IMAGE_PIXELS` | 12,000,000 |
| `EXTRACTION_MAX_CALLS_PER_PAGE` | 96 |
| `EXTRACTION_REGION_RETRIES` | 3 |
| `EXTRACTION_PAGE_TIMEOUT_SECONDS` | 450 |
| `EXTRACTION_PAGES_PER_TASK` | 2 |
| `EXTRACTION_MAX_EVIDENCE_BYTES` | 512 MiB |
| `EXTRACTION_WORD_TIMEOUT_SECONDS` | 120 |

Background workers save each completed page before publishing a continuation after two new pages. Continuations do not consume the failed-task retry budget. Source/config/prompt/revision/checksum identities protect resume; completed pages are not reread. Word rendering uses a private process profile with frozen fields and without provider credentials in its environment. Existing worker processes isolate native parser execution; rendering is sequential within each job, not threaded across PDF pages.

Limits fail closed. Documents requiring more evidence, clearer pixels, larger regional output budgets, unsupported native structures, or unavailable fonts/models remain drafts. Resource limits and human review are acceptance gates, not an assertion that arbitrary textbooks have been benchmarked. The archive is bounded and assembled in memory; size settings must fit worker memory. Human-adjudicated educational benchmarks and live NVIDIA/renderer checks are deployment gates.

## Verification

From `backend`:

```powershell
.venv/Scripts/python.exe -m pytest tests/test_hybrid_extraction.py tests/test_extraction_api.py tests/test_ingestion.py tests/test_config.py tests/test_object_store.py -q
.venv/Scripts/python.exe tests/check_nvidia_vision_runtime.py
.venv/Scripts/python.exe tests/check_local_vision_runtime.py
```

The last command is a live NVIDIA check and requires credentials. The regression tests use synthetic source fixtures and controlled model responses. They inject missing paragraphs/options, numeric sign and critical-word changes, truncated outputs, duplicate/missing pages, missing crops, broken relationships, altered originals, stale revisions and unauthorized indexing text. An adjudicated reference also detects errors shared by both extraction channels.

From `frontend`, run `npm test -- src/components/extraction-review-modal.test.tsx src/lib/api.test.ts` and `npm run typecheck`.

For an actual labeled benchmark:

```powershell
python -m northstar_api.services.extraction_benchmark reference.json extracted.json
```

A reference specifies `source_sha256`, `adjudicated_by`, and `pages` with `number`, exact `text`, and source-aligned `blocks` (`id`, `text`, optional `cells`, `latex`, `relationships`, `options`). The evaluator reports text exact matches, character alignment errors, block recall, order, cell values/spans, header associations, critical tokens, equations, options and relationships separately. Character alignment error uses difflib alignment, not minimum-edit-distance CER. No benchmark score is substituted for source-based release checks.
