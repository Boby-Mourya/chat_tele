# Course-aware knowledge preparation and tutoring

Implementation branch: `feature/course-aware-knowledge-20260917`.

This change separates the teacher's knowledge-publication workflow from the student's study selection. It reuses the existing file upload, extraction review, database, NVIDIA adapter, Celery/RabbitMQ and WhatsApp infrastructure. It does not change any model/provider configuration or create a fine-tuning pipeline.

## Administration workflow

Open **Education -> Course knowledge** at `/education/knowledge`. The page accepts `agentId` and `courseId` query parameters. Select an Education Agent, course, curriculum, paper or explicit overview/mixed-paper upload, optional batch, material type and language.

Configure a curriculum and its papers, bind matching batches, and assign authorized papers to each enrollment. An enrollment's selected paper must be one of its authorized papers. Batch/curriculum bindings are deliberately immutable: use a new batch for a new curriculum. Administration requires Education and Knowledge permissions; agent-restricted principals are checked on the new agent-scoped routes.

Normal Education uploads use the course-aware upload endpoint. Source metadata and the ingestion job are persisted together before processing. The old generic Education upload endpoint now returns an actionable 409 rather than starting an unassigned normal upload. Existing unassigned sources remain an administrative inbox; they are never implicitly shared with students.

After the existing extraction review has completed, prepare an immutable source snapshot. File snapshots require verified extraction evidence and a matching checksum/revision. Native text snapshots retain the supplied text. Mutable website and sitemap sources are not accepted as immutable course releases; provide a reviewed file or text version instead.

Review the source blocks and original source unit side by side. Assign specific blocks to a course/curriculum/paper/batch tuple. A mixed-paper file needs separate assignments; `paperId = null` is allowed only for deliberately approved course-overview material. Linked question/options/solution blocks must be selected together. Large atomic units are blocked for review rather than silently split through a table or question.

A possible course mismatch is flagged using explicit course names/codes in the title or headings. Shared terminology alone is not treated as a mismatch. These are conservative, inspectable warnings, not an automatic semantic classifier. Staff choose and approve the final mapping; advanced semantic paper/topic/learning-objective suggestion is not implemented by this branch.

Approval is bound to the exact source/extraction hash and mapping revision. Changing a mapping invalidates its approval and index readiness. Index preparation is idempotent per assignment revision, validates vector count/dimensions and content/source references, and remains unpublished. A complete candidate manifest is checked again before its active release pointer is changed using an expected epoch. A failed candidate does not switch that pointer.

A release manifest replaces the preceding manifest; include every assignment and reviewed artifact that should remain available. For ordinary content replacement that must keep the old safe content available, create a **new assignment** and publish a replacement manifest. Editing an existing published assignment is intentionally fail-closed: its old approval no longer authorizes the edited revision.

Withdraw a source version or assignment to block it immediately, including dependent generated material. A withdrawal does not wait for a replacement release. Historical messages remain in the audit record, but stale evidence-bearing responses are excluded from new tutoring context.

## Source evidence and derived material

The review ZIP contains `extracted_content.txt`, `structured_content.json`, `course_mapping.json`, and `validation_report.json`. Reports identify source/block boundaries and preserve reviewed structured fields. Coverage and semantic correctness are not the same thing: the report does not fabricate an accuracy percentage.

Source snapshots preserve the existing extraction representation and original references. Word/text units are not assigned invented printed page numbers. A defined rendered Word version can have version-bound page references. This branch does not replace or certify the pre-existing extraction engine; its native/vision behavior and review limitations remain relevant.

Generated summaries, flashcards, practice questions, translations and worked examples name their source assignments and blocks, generation configuration, and dependency fingerprints. Their audience is the intersection of all inputs. Drafts require teacher review and later release inclusion. Practice answer-key validation is a separate explicit flag, not an automatic consequence of generation or publication. This branch does not introduce an objective-grading engine.

The student-scope preview uses the same active enrollment/release/assignment filter as tutoring. It can download only a currently authorized text excerpt. It does not expose the full mixed-access document or page image. Original-page and full extraction review are staff operations, not student download routes.

## Student workflow and authorization

The existing dedicated WhatsApp Cloud API worker verifies the sender, loads valid enrollments, and accepts an explicit course code/name or a number from the current menu. The student then chooses an authorized paper or course overview. `courses` and `papers` reopen the relevant menus. Choosing or switching a course updates selection/history only; it never creates an extraction or indexing job.

The shared tutoring coordinator checks tenant, workspace, agent, active student/enrollment, access dates, course, curriculum, batch binding, selected authorized paper, current release, exact approved assignment revision, and withdrawal state. No selected paper means overview-only retrieval, not every paper. The same predicates constrain vector search, full-text search, and preview/excerpt queries. This branch reuses the repository's existing PostgreSQL vector/keyword architecture; it does not add a separate graph or document-tree retrieval engine.

Conversation history and idempotent response reuse require the current enrollment/paper/release/access fingerprint. Completed historical answers from a different or revoked scope are not blindly fed into the model. WhatsApp replies revalidate verified identity, enrollment and evidence again before sending each response chunk.

Menu responses have durable receipts so retrying a numeric selection does not reinterpret it as a new tutoring question. Database state and per-chunk provider IDs support retries. As with the existing provider integration, delivery cannot be claimed exactly-once when the provider accepts a request but its acknowledgement is lost.

When authorized published material is missing, the selected course remains selected. Only the existing configured web/general fallback policy may be used, without private conversation history, and the answer is labeled as not verified against the course library. An academic-review item is created. Neither student submissions nor review-queue resolutions automatically modify shared knowledge.

The new selection UX is integrated into the dedicated WhatsApp inbound worker. Existing authenticated chat/widget entry points use the shared course-aware coordinator once they have an authorized Education conversation. This branch does not add a new student onboarding/session API or course-menu UX for every other messaging channel.

## API map

All paths below are relative to the application's existing `/api/v1` prefix.

| Scope | Operations |
| --- | --- |
| `/education/knowledge` | GET catalog; POST curricula; POST papers; PUT batch-curriculum |
| `/agents/{agentId}/education-knowledge` | GET status; POST uploads; PUT enrollment access |
| `.../sources/{sourceId}` | POST snapshot |
| `.../versions/{versionId}` | GET blocks; GET report ZIP; POST withdraw |
| `.../assignments` | POST create; PUT revision; POST approve; POST prepare; POST withdraw |
| `.../releases` | POST candidate; POST `{releaseId}/publish` with expected epoch |
| `.../artifacts` | POST draft generation; GET exact artifact; POST approval |
| `.../preview` | POST enrolled-student retrieval; POST `excerpts/{entryId}` for scoped text |
| `.../academic-reviews/{reviewId}` | PATCH review status without automatically changing the library |

Use workspace headers and the normal authenticated session. These administration APIs do not accept a model-generated authorization filter or trust a submitted course label as a grant.

## Worker deployment and rollout

Do not roll this feature directly into production before the integration, database and provider checks below pass. No production database migration or deployment was performed while implementing the branch.

There are two additive migrations after the existing `0044_hybrid_extraction_review`: `0045_course_knowledge_releases` and `0046_course_study_receipts`. The migration definitions are frozen, include PostgreSQL tenant RLS policies, and do not import mutable live models. Back up a staging database first, use the same embedding dimension as the existing model configuration, and apply them through the existing migration process:

```bash
cd backend
uv sync --all-groups --frozen
uv run alembic upgrade head
```

The regular document worker registers `northstar.prepare_course_assignment` on `ingest.source`. It remains separate from the existing WhatsApp worker queues. The additive Compose override starts a durable index dispatcher using the existing job dispatcher's service database identity, broker configuration, network boundaries and migration prerequisite:

```bash
docker compose -f compose.yaml -f compose.course-knowledge.yaml config
docker compose -f compose.yaml -f compose.course-knowledge.yaml up -d --build
```

Preserve any additional environment-specific Compose files already used by your deployment. These are rollout commands, not evidence that containers were started during implementation. Kubernetes installations need an equivalent deployment for `python -m northstar_api.workers.course_knowledge_dispatcher` using the existing worker image, secrets, service database identity and network policy; no new Kubernetes deployment was applied or certified here.

The dispatcher polls due queued/preparing assignment revisions, sends only scoped identifiers to the broker, and tracks bounded attempts and leases. A worker crash may cause a duplicate delivery; the task rechecks exact approval and unique index entries. Broker failure leaves a durable intent. After retries are exhausted, the assignment shows a failure that staff can explicitly retry.

**Migration alone does not grant access to legacy material.** Before enabling student traffic, configure curricula, batch bindings and enrollment paper grants, then snapshot, map, review and publish the existing sources. The new runtime intentionally refuses to fall back to legacy unscoped Education chunks. Support and lead-generation agents retain the existing generic upload/chat path.

## Verification evidence and remaining gates

| Check | Result during implementation |
| --- | --- |
| Pure policy and Pydantic contract tests | 58 passed in the available local environment |
| Python syntax on locally prepared changed files and integration tests | Passed |
| TypeScript transpilation syntax on the new page and API client | Passed; not a full application type-check or build |
| Real application API regression suite | Added, not executed locally; the complete repository runtime/dependencies were unavailable |
| PostgreSQL migrations, RLS, vector/FTS execution and concurrent release/withdrawal tests | Not executed |
| Full frontend build, browser behavior and accessibility verification | Not executed |
| Live NVIDIA extraction/generation, object storage, RabbitMQ and WhatsApp delivery | Not exercised against an authorized deployment |
| Hosted GitHub Actions | Inspected runs failed before executing any job steps; no hosted test pass is claimed |

`backend/tests/test_course_knowledge_policy.py` exercises explicit audience boundaries, overview-only behavior, derived permission intersections, block isolation, linked content, immutable approval fingerprints, page-reference rules, invalid vectors, course/menu selection and request validation. The count above is for these isolated checks, not the entire application test suite.

`backend/tests/test_course_knowledge_api.py` adds real application-fixture regressions for upload idempotency, review/index/publication, scoped previews and excerpts, source withdrawal, stale approval, failed-candidate pointer preservation, course switching without new ingestion jobs, and the destination guard. Its model calls are test doubles, not live-provider certification.

The branch-specific CI workflow installs locked dependencies, checks Python syntax and the migration graph, runs the new policy/API regressions using the actual application, and type-checks/builds the whole frontend. It does not remove unrelated routers or convert failures into successes. A migration graph check is not a PostgreSQL migration execution test.

Before merge, execute those jobs on a working runner, check compatibility of older Education tests with the intentionally tightened upload/release contract, run the PostgreSQL upgrade and rollback on representative staging data, test concurrent publication/withdrawal and broker retry recovery, exercise the UI, and complete the signed WhatsApp -> selection -> authorized retrieval -> cited reply flow against the configured services. Advanced automatic curriculum classification remains a separate enhancement rather than a completed capability of this branch.
