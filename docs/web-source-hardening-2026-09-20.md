# Web-source hardening tranche — 20 September 2026

Scope: additional F02/F11 mitigations and B01 progress evidence bookkeeping from the production audit, implemented over `b915fd9ba5d6fc5ba279b768e48635e557cbfe3b`. This is not completion of the 26-package specification.

## Active runtime changes

`services/safe_fetch.py` retains DNS/IP pinning and TLS hostname verification. Optional hostname and port grants are enforced before DNS on every hop, including redirects. An empty grant denies all. Port zero is rejected rather than being mistaken for the default port. A whole-fetch deadline bounds DNS, retries, redirects and response reads. HTTPS redirects cannot downgrade to HTTP. Invalid text decoding fails instead of replacing bytes silently. Requests ask for identity encoding and reject compressed responses before decompression; the byte budget is checked before extending the aggregate buffer.

`modules/knowledge/web_sources.py` admits only bounded HTTP(S) `urlset` sitemaps. DTDs, entity declarations, nested sitemap indexes, malformed or missing locations, unsupported ports and out-of-scope locations reject the candidate before page processing. Page batches are bounded to at most five concurrent requests. URL limits are rejection limits, not silent clipping. Page failures, empty responses, character exhaustion (including source headers/separators), or deadline exhaustion cannot return a searchable partial result. Cancellation propagates.

Meaningful query parameters, their order and trailing slashes are retained. Only fragments are discarded. Exact duplicate locations are counted and fetched once. The manifest records requested/final page URLs, statuses, timestamps and visible-text hashes. It describes guarded visible-text processing, not complete website/HTML/browser fidelity.

`modules/knowledge/ingestion.py` calls the bounded adapter before embedding. Successful sitemap pages are chunked independently, with URL/timestamp/text-hash provenance. A successful knowledge snapshot includes the ingested source's crawl manifest. A failed crawl records its manifest in the existing job error JSON after rollback and presents an incomplete-source error. No schema migration is needed for these existing JSON fields.

`services/crawler.py` retains compatibility names but its old `requests`/Playwright network entrypoints fail immediately without network or browser I/O. It cannot be used as an alternate unsafe transport. The local JSON export helper remains; caller-selected directory paths are rejected.

## Compatibility and rollout

Browser rendering and automatic crawler discovery remain disabled until a network-isolated egress worker is qualified. Sitemap indexes, compressed HTTP responses, cross-host sitemap redirects/locations and nonstandard sitemap ports are explicitly unsupported by this tranche. Ordinary guarded fetch calls retain public-host/nonstandard-port support unless their caller supplies a scope, but all callers now reject port zero, HTTPS downgrade, invalid decoding and compressed responses. A server must honor `Accept-Encoding: identity` or the source fails visibly.

Existing queued task names, model identifiers, NVIDIA configuration, database migrations, tenant IDs and source IDs are unchanged. This patch does not turn an old incomplete crawl into a qualified release; reingest it through the new adapter. Do not re-enable the retired browser crawler to work around a rejected source.

## Executed local evidence

The targeted source copies for existing `safe_fetch.py` and `ingestion.py` were checked against their Git blob identities before edits. Local execution used Python 3.13, the installed HTTPX/pytest environment and mocked DNS/HTTP transports; it was not the repository's locked production image.

```bash
PYTHONPATH=backend/src python -m pytest --noconftest -q \
  backend/tests/test_safe_fetch.py backend/tests/test_web_sources.py
python scripts/test_implementation_progress.py -v
python scripts/implementation_progress.py --check docs/production-implementation-progress.md --json
python -m compileall -q backend/src scripts
```

Observed: **69 transport/crawl regression tests passed**, **14 progress-accounting tests passed**, generated-report consistency passed, and selected-source compilation passed. These 83 local tests are not the audit's 84 end-to-end acceptance scenarios. `--noconftest` deliberately isolates transport/parser checks from the full application fixture; no database or model integration is inferred from this run.

The existing full-application sitemap test was updated from silently accepting a same-host subset to requiring explicit rejection of an out-of-scope manifest. It remains subject to the normal application suite. Full application imports/tests, Ruff formatting/lint, mypy, PostgreSQL/pgvector, broker/storage, browser-isolation, load/restore and live-provider tests were not executed here. Dependency installation was unavailable in the execution environment. Main's previously observed CI failures and skipped topology gate are still blockers until a successful exact-artifact run exists.

## Remaining work

This does not supply an immutable raw HTML/page-snapshot store, complete historical source-generation membership, a citation UI resolving every stored page locator, tokenizer-aware chunking, ingestion leases/fencing, or deployed browser/network isolation. It does not qualify all F02/F11 acceptance outcomes. The retained ordinary ingestion lifecycle can still mark a source failed during reindexing; retaining a last-good published generation is B09/B11 work, not solved by these crawl guards.

The progress registry carries all B01–B26 packages and T01–T84 scenarios. Only T32 has partial local evidence added here; it is not marked fully passed. Credits are manual engineering estimates. Exact-SHA release signoffs require separate environment evidence and all mandatory exits.
