# Northstar Help Center Operations Guide

## Scope

The Help Center is an authenticated product-help surface inside the existing **Help** sidebar entry. It supports the existing workspace roles only: `owner`, `admin`, `member`, and `analyst`. It does not add a Super Admin role or a second application shell.

## User routes

- `/help` — home, role-aware recommendations, categories, recently viewed, support entry
- `/help/search?q=...` — full-text/semantic Help search
- `/help/categories/:slug` — category guides
- `/help/articles/:slug` — article reader, TOC, previous/next, related guides, feedback
- `/help/ask` — grounded Northstar Help AI
- `/help/support` — support request form and request history
- `/help/support/:requestId` — request detail

## Backend API

All routes are under `/api/v1/help` (and the repository's existing `/v1` compatibility alias) and require the current authentication flow.

Main endpoint groups:

- `GET /help`
- `GET /help/categories`
- `GET /help/categories/{slug}`
- `GET /help/articles/{slug}`
- `GET /help/search`
- `POST /help/articles/{article_id}/feedback`
- `POST /help/ask`
- `POST /help/events`
- `POST /help/support-requests`
- `GET /help/support-requests`
- `GET /help/support-requests/{request_id}`

## Content ownership

Official Northstar Help articles are docs-as-code under `backend/help_content/`.

Customer knowledge remains in the existing customer RAG pipeline. Do not load Northstar Help articles into `KnowledgeSource`/`DocumentChunk`, and do not retrieve customer knowledge from Help AI.

Each article uses YAML front matter:

```yaml
---
slug: create-agent
title: Create an agent
summary: Create a new Northstar AI agent.
category: agents
roles: [owner, admin]
keywords: [agent, create, chatbot]
featured: true
sort_order: 20
---
```

Allowed roles are exactly `owner`, `admin`, `member`, and `analyst`.

## Adding or updating articles

1. Choose the existing category folder under `backend/help_content/`.
2. Add or edit a Markdown file with valid front matter.
3. Use exact product labels and document only behavior that exists in the codebase.
4. Run backend compilation and frontend checks.
5. Restart the API (when `HELP_CONTENT_SYNC_ON_STARTUP=true`) to sync changed content.

The content sync is idempotent. It hashes article content, only rebuilds chunks/embeddings when content changes, and archives removed docs rather than immediately deleting historical article records.

## Search and Help AI

Search works without NVIDIA. It combines role-filtered lexical ranking with semantic retrieval when embeddings are available. Help AI retrieves only role-visible `HelpArticleChunk` evidence and then calls the existing NVIDIA grounded-generation adapter.

If NVIDIA is unavailable:

- Help home/articles continue to work.
- lexical Help search continues to work.
- Ask Help AI returns a controlled unavailable state and relevant article suggestions.

## Support requests

The support destination is resolved from the workspace white-label `supportEmail`, with `support@northstar.ai` as fallback. A configured external support URL is exposed only when it is a valid `http` or `https` URL.

Safe diagnostics are allow-listed. Tokens, passwords, API keys, credentials, cookies, authorization headers, conversation bodies, and customer knowledge are not automatically collected.

`owner` and `admin` can see requests from their own workspace. `member` and `analyst` can see only requests they created. This is enforced in the backend and by PostgreSQL tenant isolation.

## Database migration

Migration: `backend/migrations/versions/0005_help_center.py`

It adds only Help Center structures:

- `help_categories`
- `help_articles`
- `help_article_chunks`
- `help_article_feedback`
- `help_events`
- `help_support_requests`

No existing application table is dropped or modified destructively.

Run using the repository's normal Alembic workflow.

## Configuration

Relevant environment variables:

- `HELP_CONTENT_SYNC_ON_STARTUP`
- `HELP_SEARCH_PAGE_SIZE_MAX`
- `HELP_SEARCH_CANDIDATE_LIMIT`
- `HELP_AI_RATE_LIMIT_PER_MINUTE`
- `HELP_AI_MIN_SCORE`

They are documented in the root and backend `.env.example` files.

## Deployment packaging

`backend/Dockerfile` copies `help_content` into both build and runtime stages. Keep this copy step if the Docker layout changes; otherwise production startup cannot sync the docs-as-code content.

## Quality checks

Before merging/pushing Help changes, run the repository's normal checks plus:

```bash
cd frontend
npm run typecheck
npm run lint

cd ..
python -m compileall -q backend/src backend/tests backend/migrations
git diff --check
```

When dependencies/services are available, also run frontend Vitest/build and backend pytest/Alembic upgrade-downgrade checks.

## Security invariants

- All Help APIs are authenticated.
- Role filtering happens before search ranking and Help AI evidence generation.
- Product Help and customer knowledge remain separate.
- Workspace admins are not global Help article editors.
- Support records remain tenant-scoped.
- Raw HTML is not rendered from Help Markdown.
- External support links use safe protocols and safe browser link attributes.
- Help analytics accept only narrow, known event types and visible article IDs.
