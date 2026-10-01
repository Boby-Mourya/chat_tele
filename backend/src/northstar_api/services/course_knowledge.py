"""Versioned course knowledge over the existing ingestion and NVIDIA services.

Mutators leave commit/rollback to their caller. The PostgreSQL release pointer is
only switched after all candidate rows are verified. There is no all-course RAG
fallback, and neither grants nor course selection enqueue ingestion work.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Float, bindparam, func, or_, select, text, type_coerce, update
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.course_knowledge_models import (
    CourseBatchCurriculum,
    CourseCurriculum,
    CourseDerivedArtifact,
    CourseEnrollmentAccess,
    CourseIndexEntry,
    CourseKnowledgeRelease,
    CourseMaterialAssignment,
    CoursePaper,
    CourseReleaseHead,
    CourseReleaseMember,
    CourseSourceVersion,
)
from northstar_api.services.course_knowledge_policy import (
    Audience,
    KnowledgePolicyError,
    LearnerScope,
    audience_intersection,
    canonical_blocks,
    fingerprint,
    mapping_fingerprint,
    mismatch_warnings,
    scoped_chunks,
    selected_blocks,
    text_record,
    validate_vectors,
)


@dataclass(frozen=True, slots=True)
class Boundary:
    tenant_id: UUID
    workspace_id: UUID
    agent_id: UUID

    def values(self) -> dict[str, UUID]:
        return asdict(self)

    def filters(self, model: Any) -> tuple[Any, ...]:
        return (model.tenant_id == self.tenant_id, model.workspace_id == self.workspace_id, model.agent_id == self.agent_id)


async def scoped_row(session: AsyncSession, model: Any, identity: UUID, boundary: Boundary, *, lock: bool = False) -> Any:
    query = select(model).where(model.id == identity, *boundary.filters(model)).execution_options(populate_existing=True)
    if lock:
        query = query.with_for_update()
    row = await session.scalar(query)
    if row is None:
        raise KnowledgePolicyError("The requested course knowledge record does not exist in this workspace and agent")
    return row


async def _serialize(session: AsyncSession, key: str) -> None:
    if session.bind is not None and session.bind.dialect.name == "postgresql":
        await session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": key})


async def validate_destination(session: AsyncSession, boundary: Boundary, destination: dict[str, Any], *, upload: bool = False) -> tuple[Any, CourseCurriculum]:
    from northstar_api.education import EducationCourse
    from northstar_api.education_batches import EducationBatch

    course = await session.scalar(select(EducationCourse).where(
        EducationCourse.id == UUID(str(destination["course_id"])), EducationCourse.tenant_id == boundary.tenant_id,
        EducationCourse.workspace_id == boundary.workspace_id, EducationCourse.status == "active",
    ))
    curriculum = await session.scalar(select(CourseCurriculum).where(
        CourseCurriculum.id == UUID(str(destination["curriculum_id"])), CourseCurriculum.tenant_id == boundary.tenant_id,
        CourseCurriculum.workspace_id == boundary.workspace_id, CourseCurriculum.active.is_(True),
    ))
    if course is None or curriculum is None or curriculum.course_id != course.id:
        raise KnowledgePolicyError("Choose an active course and one of its configured curricula")
    paper_id = destination.get("paper_id")
    if paper_id:
        paper = await session.scalar(select(CoursePaper).where(
            CoursePaper.id == UUID(str(paper_id)), CoursePaper.curriculum_id == curriculum.id,
            CoursePaper.tenant_id == boundary.tenant_id, CoursePaper.workspace_id == boundary.workspace_id,
            CoursePaper.active.is_(True),
        ))
        if paper is None:
            raise KnowledgePolicyError("The selected paper does not belong to this curriculum")
        allowed_topics = {str(t.get("id")) for t in paper.topics}
        if not set(destination.get("topic_ids") or []) <= allowed_topics:
            raise KnowledgePolicyError("A selected topic does not belong to this paper")
    elif not (destination.get("overview") or (upload and destination.get("mixed_papers"))):
        raise KnowledgePolicyError("Choose a paper, explicit course overview, or mixed-papers upload")
    if destination.get("overview") and (paper_id or destination.get("mixed_papers")):
        raise KnowledgePolicyError("Course overview cannot also mean a paper or mixed papers")
    if not paper_id and destination.get("topic_ids"):
        raise KnowledgePolicyError("Paper topic mappings require a selected paper")
    batch_id = destination.get("batch_id")
    if batch_id:
        batch = await session.scalar(select(EducationBatch).where(
            EducationBatch.id == UUID(str(batch_id)), EducationBatch.course_id == course.id,
            EducationBatch.tenant_id == boundary.tenant_id, EducationBatch.workspace_id == boundary.workspace_id,
            EducationBatch.status == "active",
        ))
        binding = await session.scalar(select(CourseBatchCurriculum).where(
            CourseBatchCurriculum.batch_id == UUID(str(batch_id)), CourseBatchCurriculum.curriculum_id == curriculum.id,
            CourseBatchCurriculum.tenant_id == boundary.tenant_id, CourseBatchCurriculum.workspace_id == boundary.workspace_id,
        ))
        if batch is None or binding is None:
            raise KnowledgePolicyError("The selected batch must be bound to this course curriculum")
    return course, curriculum


def assignment_audience(assignment: CourseMaterialAssignment) -> Audience:
    return Audience(
        str(assignment.tenant_id), str(assignment.workspace_id), str(assignment.agent_id),
        str(assignment.course_id), str(assignment.curriculum_id),
        str(assignment.paper_id) if assignment.paper_id else None,
        str(assignment.batch_id) if assignment.batch_id else None, assignment.overview,
    )


def assignment_digest(assignment: CourseMaterialAssignment, source: CourseSourceVersion) -> str:
    return mapping_fingerprint(
        source.source_checksum, source.record_hash, assignment_audience(assignment), assignment.block_ids,
        assignment.revision, f"{assignment.material_type}:{assignment.language}", assignment.topic_ids,
    )


async def snapshot_source(session: AsyncSession, boundary: Boundary, source_id: UUID) -> CourseSourceVersion:
    from northstar_api.models import KnowledgeKind, KnowledgeSource, KnowledgeStatus
    from northstar_api.services.hybrid_extraction import ExtractionPackage
    from northstar_api.services.object_store import object_store

    await _serialize(session, f"course-snapshot:{boundary.workspace_id}:{source_id}")
    source = await scoped_row(session, KnowledgeSource, source_id, boundary, lock=True)
    if source.kind == KnowledgeKind.FILE:
        if source.status != KnowledgeStatus.READY or not source.extraction_key or not source.extraction_key.startswith(f"extractions/{boundary.tenant_id}/{source.id}/"):
            raise KnowledgePolicyError("Finish the existing extraction review and indexing before preparing course assignments")
        archive, _ = await object_store.download(source.extraction_key, limit_bytes=1024**3)
        package = ExtractionPackage.from_archive(archive, source_sha256=source.checksum, revision=source.revision)
        record = package.record
        if record.get("review_status") != "verified_release" or not record.get("release_eligible"):
            raise KnowledgePolicyError("The extraction still has unresolved review blockers")
        processing_hash = str(record.get("config_sha256") or fingerprint({"record": record, "configuration": "unknown_legacy"}))
    elif source.kind == KnowledgeKind.TEXT:
        if source.status != KnowledgeStatus.READY or not source.content:
            raise KnowledgePolicyError("The text source has not finished ingestion")
        record = text_record(source.content, source.checksum, source.revision)
        processing_hash = fingerprint({"extractor": "native-text", "version": 1})
    else:
        raise KnowledgePolicyError("Course releases require immutable file or text uploads, not mutable website/sitemap sources")
    blocks = canonical_blocks(record)
    digest = fingerprint(record)
    existing = await session.scalar(select(CourseSourceVersion).where(
        *boundary.filters(CourseSourceVersion), CourseSourceVersion.source_id == source.id,
        CourseSourceVersion.source_revision == source.revision, CourseSourceVersion.processing_hash == processing_hash,
        CourseSourceVersion.record_hash == digest,
    ))
    if existing:
        if existing.withdrawn:
            raise KnowledgePolicyError("This source version has been withdrawn; upload a new reviewed version")
        return existing
    report = {
        "extraction_checks": record.get("checks", []),
        "extraction_metrics": record.get("metrics", {}),
        "coverage": {"source_units": len(record.get("pages", [])), "extracted_blocks": len(blocks)},
        "text_fidelity": "existing extraction review passed" if source.kind == KnowledgeKind.FILE else "native text; mapping review required",
        "tables_formulas": "preserved as atomic source blocks; semantic correctness is not guaranteed",
        "citation_integrity": "stable source/block references; DOCX units are not invented page numbers",
        "course_mapping": "requires explicit assignment approval",
        "access_boundaries": "no student access until active release membership",
    }
    version = CourseSourceVersion(
        **boundary.values(), source_id=source.id, source_revision=source.revision,
        source_checksum=source.checksum, processing_hash=processing_hash, record_hash=digest,
        title=source.name, original_object_key=source.object_key, extraction_key=source.extraction_key,
        record=record, validation=report, withdrawn=False,
    )
    session.add(version)
    await session.flush()
    return version


async def save_assignment(session: AsyncSession, boundary: Boundary, payload: dict[str, Any], *, assignment_id: UUID | None = None) -> CourseMaterialAssignment:
    await validate_destination(session, boundary, payload)
    source = await scoped_row(session, CourseSourceVersion, UUID(str(payload["source_version_id"])), boundary)
    if source.withdrawn or fingerprint(source.record) != source.record_hash:
        raise KnowledgePolicyError("The source version is withdrawn or its extraction integrity check failed")
    chosen = selected_blocks(canonical_blocks(source.record), payload["block_ids"])
    scoped_chunks(canonical_blocks(source.record), payload["block_ids"])
    # Use the same head -> assignment lock order as publication and withdrawal.
    await release_head(session, boundary, UUID(str(payload["course_id"])), UUID(str(payload["curriculum_id"])), lock=True)
    if assignment_id:
        assignment = await scoped_row(session, CourseMaterialAssignment, assignment_id, boundary, lock=True)
        if assignment.revision != payload.get("expected_revision"):
            raise KnowledgePolicyError("Mapping changed; reload before saving")
        if assignment.status == "withdrawn":
            raise KnowledgePolicyError("Withdrawn assignments cannot be revived; create a new assignment")
        # Audience/source revisions stay under the original course release head.
        if assignment.course_id != UUID(str(payload["course_id"])) or assignment.curriculum_id != UUID(str(payload["curriculum_id"])):
            raise KnowledgePolicyError("Create a separate assignment to reuse this source for a different course/curriculum")
        assignment.revision += 1
    else:
        key = str(payload["idempotency_key"])
        await _serialize(session, f"course-assignment:{boundary.workspace_id}:{boundary.agent_id}:{key}")
        previous = await session.scalar(select(CourseMaterialAssignment).where(*boundary.filters(CourseMaterialAssignment), CourseMaterialAssignment.idempotency_key == key))
        if previous:
            comparable = (str(previous.source_version_id), str(previous.course_id), str(previous.curriculum_id), sorted(previous.block_ids), str(previous.paper_id or ""), str(previous.batch_id or ""), previous.overview, previous.language, previous.material_type, sorted(previous.topic_ids))
            requested = (str(payload["source_version_id"]), str(payload["course_id"]), str(payload["curriculum_id"]), sorted(payload["block_ids"]), str(payload.get("paper_id") or ""), str(payload.get("batch_id") or ""), bool(payload.get("overview")), payload.get("language", "English"), payload.get("material_type", "notes"), sorted(payload.get("topic_ids") or []))
            if comparable != requested:
                raise KnowledgePolicyError("This idempotency key was already used for a different mapping")
            return previous
        assignment = CourseMaterialAssignment(**boundary.values(), idempotency_key=key, revision=1)
        session.add(assignment)
    for field in ("source_version_id", "course_id", "curriculum_id"):
        setattr(assignment, field, UUID(str(payload[field])))
    for field in ("paper_id", "batch_id"):
        setattr(assignment, field, UUID(str(payload[field])) if payload.get(field) else None)
    assignment.overview = bool(payload.get("overview"))
    assignment.block_ids = [b["id"] for b in chosen]
    assignment.topic_ids = list(payload.get("topic_ids") or [])
    assignment.language = payload.get("language", "English")
    assignment.material_type = payload.get("material_type", "notes")
    assignment.status = "review"
    assignment.index_status = "not_prepared"
    assignment.index_error = None
    assignment.approval_fingerprint = None
    assignment.approved_by = None
    assignment.approved_at = None
    assignment.review_reason = ""
    from northstar_api.education import EducationCourse
    courses = (await session.scalars(select(EducationCourse).where(EducationCourse.tenant_id == boundary.tenant_id, EducationCourse.workspace_id == boundary.workspace_id))).all()
    current = next(c for c in courses if c.id == assignment.course_id)
    assignment.validation = {
        "mapping_review_required": True,
        "warnings": mismatch_warnings(source.title, chosen, [current.code, current.name], [(str(c.id), [c.code, c.name]) for c in courses if c.id != current.id]),
        "block_count": len(chosen), "source_record_hash": source.record_hash,
    }
    await invalidate_head(session, boundary, assignment.course_id, assignment.curriculum_id)
    await session.flush()
    return assignment


async def approve_assignment(session: AsyncSession, boundary: Boundary, assignment_id: UUID, *, expected_revision: int, expected_source_hash: str, reviewer_id: UUID, reason: str, mismatch_confirmed: bool) -> CourseMaterialAssignment:
    assignment = await scoped_row(session, CourseMaterialAssignment, assignment_id, boundary, lock=True)
    source = await scoped_row(session, CourseSourceVersion, assignment.source_version_id, boundary)
    if assignment.status == "withdrawn" or source.withdrawn:
        raise KnowledgePolicyError("Withdrawn material cannot be approved")
    if assignment.revision != expected_revision or source.record_hash != expected_source_hash or fingerprint(source.record) != source.record_hash:
        raise KnowledgePolicyError("The extraction or mapping changed; review the current version")
    if assignment.validation.get("warnings") and not mismatch_confirmed:
        raise KnowledgePolicyError("Resolve or explicitly confirm the possible course mismatch before approving")
    if not reason.strip():
        raise KnowledgePolicyError("Record the source-verification and audience review decision")
    await validate_destination(session, boundary, {**asdict(assignment_audience(assignment)), "topic_ids": assignment.topic_ids})
    scoped_chunks(canonical_blocks(source.record), assignment.block_ids)
    assignment.approval_fingerprint = assignment_digest(assignment, source)
    assignment.status = "approved"
    assignment.approved_by = reviewer_id
    assignment.approved_at = datetime.now(UTC)
    assignment.review_reason = reason.strip()
    assignment.validation = {**assignment.validation, "mapping_review_required": False, "mismatch_confirmed": mismatch_confirmed}
    await session.flush()
    return assignment


async def prepare_assignment_index(session: AsyncSession, boundary: Boundary, assignment_id: UUID, expected_revision: int) -> CourseMaterialAssignment:
    from northstar_api.config import get_settings
    from northstar_api.services.llm import nvidia_adapter

    assignment = await scoped_row(session, CourseMaterialAssignment, assignment_id, boundary, lock=True)
    source = await scoped_row(session, CourseSourceVersion, assignment.source_version_id, boundary)
    if assignment.revision != expected_revision or assignment.status != "approved" or source.withdrawn or assignment.approval_fingerprint != assignment_digest(assignment, source):
        raise KnowledgePolicyError("Indexing requires the exact approved, non-withdrawn mapping revision")
    chunks = scoped_chunks(canonical_blocks(source.record), assignment.block_ids)
    existing = (await session.scalars(select(CourseIndexEntry).where(*boundary.filters(CourseIndexEntry), CourseIndexEntry.assignment_id == assignment.id, CourseIndexEntry.assignment_revision == assignment.revision).order_by(CourseIndexEntry.ordinal))).all()
    settings = get_settings()
    if len(chunks) > settings.knowledge_max_chunks:
        raise KnowledgePolicyError("This assignment exceeds the configured knowledge chunk limit")
    if existing:
        verify_index(assignment, chunks, existing)
        if any(e.embedding_model != settings.nvidia_embedding_model for e in existing):
            raise KnowledgePolicyError("Embedding configuration changed; save and approve a new mapping revision before rebuilding")
        assignment.index_status = "ready"
        assignment.index_error = None
        return assignment
    approval = assignment.approval_fingerprint
    assignment.index_status = "preparing"
    # Do not hold a mapping lock while calling the provider: withdrawals must not
    # wait for embedding I/O. Recheck the exact revision under lock afterwards.
    await session.commit()
    vectors: list[list[float]] = []
    for start in range(0, len(chunks), 32):
        vectors.extend(await nvidia_adapter.embed_documents([c["content"] for c in chunks[start:start + 32]]))
    validate_vectors(vectors, len(chunks), settings.embedding_dimension)
    assignment = await scoped_row(session, CourseMaterialAssignment, assignment_id, boundary, lock=True)
    source = await scoped_row(session, CourseSourceVersion, assignment.source_version_id, boundary)
    if assignment.revision != expected_revision or assignment.status != "approved" or source.withdrawn or assignment.approval_fingerprint != approval or fingerprint(source.record) != source.record_hash:
        raise KnowledgePolicyError("The approved source or audience changed while preparing the index")
    existing = (await session.scalars(select(CourseIndexEntry).where(*boundary.filters(CourseIndexEntry), CourseIndexEntry.assignment_id == assignment.id, CourseIndexEntry.assignment_revision == expected_revision).order_by(CourseIndexEntry.ordinal))).all()
    if existing:
        verify_index(assignment, chunks, existing)
        assignment.index_status = "ready"
        assignment.index_error = None
        return assignment
    for ordinal, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True)):
        session.add(CourseIndexEntry(
            **boundary.values(), assignment_id=assignment.id, assignment_revision=assignment.revision,
            approval_fingerprint=assignment.approval_fingerprint, ordinal=ordinal, content=chunk["content"],
            content_hash=chunk["content_hash"], block_ids=chunk["block_ids"], source_references=chunk["references"],
            embedding=vector, embedding_model=settings.nvidia_embedding_model,
        ))
    assignment.index_status = "ready"
    assignment.index_error = None
    await session.flush()
    return assignment


def verify_index(assignment: CourseMaterialAssignment, chunks: list[dict[str, Any]], entries: list[CourseIndexEntry]) -> str:
    if len(chunks) != len(entries) or not entries:
        raise KnowledgePolicyError("The candidate index does not contain every expected scoped retrieval unit")
    for ordinal, (chunk, entry) in enumerate(zip(chunks, entries, strict=True)):
        if (entry.ordinal != ordinal or entry.assignment_revision != assignment.revision
            or entry.approval_fingerprint != assignment.approval_fingerprint
            or entry.content != chunk["content"] or entry.content_hash != fingerprint(entry.content)
            or entry.block_ids != chunk["block_ids"] or entry.source_references != chunk["references"]):
            raise KnowledgePolicyError("The candidate index has changed content, permissions, or source references")
    from northstar_api.config import get_settings
    validate_vectors([list(e.embedding) for e in entries], len(chunks), get_settings().embedding_dimension)
    if any(e.embedding_model != get_settings().nvidia_embedding_model for e in entries):
        raise KnowledgePolicyError("Candidate embeddings use a different model configuration")
    return fingerprint([{"id": str(e.id), "hash": e.content_hash, "blocks": e.block_ids, "revision": e.assignment_revision, "model": e.embedding_model} for e in entries])


async def release_head(session: AsyncSession, boundary: Boundary, course_id: UUID, curriculum_id: UUID, *, create: bool = False, lock: bool = False) -> CourseReleaseHead | None:
    if create or lock:
        await _serialize(session, f"course-release:{boundary.workspace_id}:{boundary.agent_id}:{course_id}:{curriculum_id}")
    query = select(CourseReleaseHead).where(*boundary.filters(CourseReleaseHead), CourseReleaseHead.course_id == course_id, CourseReleaseHead.curriculum_id == curriculum_id).execution_options(populate_existing=True)
    if lock:
        query = query.with_for_update()
    head = await session.scalar(query)
    if head is None and create:
        head = CourseReleaseHead(**boundary.values(), course_id=course_id, curriculum_id=curriculum_id, epoch=0)
        session.add(head)
        await session.flush()
    return head


async def invalidate_head(session: AsyncSession, boundary: Boundary, course_id: UUID, curriculum_id: UUID) -> None:
    await session.execute(update(CourseReleaseHead).where(*boundary.filters(CourseReleaseHead), CourseReleaseHead.course_id == course_id, CourseReleaseHead.curriculum_id == curriculum_id).values(epoch=CourseReleaseHead.epoch + 1))


async def candidate_release(session: AsyncSession, boundary: Boundary, *, course_id: UUID, curriculum_id: UUID, assignment_ids: list[UUID], artifact_ids: list[UUID], reviewer_id: UUID) -> CourseKnowledgeRelease:
    if not assignment_ids or len(set(assignment_ids)) != len(assignment_ids) or len(set(artifact_ids)) != len(artifact_ids):
        raise KnowledgePolicyError("A release requires distinct approved assignments and distinct artifact IDs")
    await validate_destination(session, boundary, {"course_id": course_id, "curriculum_id": curriculum_id, "overview": True})
    await release_head(session, boundary, course_id, curriculum_id, create=True, lock=True)
    manifest_items: list[dict[str, Any]] = []
    for identity in sorted(assignment_ids, key=str):
        assignment = await scoped_row(session, CourseMaterialAssignment, identity, boundary, lock=True)
        source = await scoped_row(session, CourseSourceVersion, assignment.source_version_id, boundary)
        if (assignment.course_id != course_id or assignment.curriculum_id != curriculum_id
            or assignment.status != "approved" or assignment.index_status != "ready" or source.withdrawn or fingerprint(source.record) != source.record_hash
            or assignment.approval_fingerprint != assignment_digest(assignment, source)):
            raise KnowledgePolicyError("Every release assignment must be approved and indexed for this exact course/curriculum")
        entries = (await session.scalars(select(CourseIndexEntry).where(*boundary.filters(CourseIndexEntry), CourseIndexEntry.assignment_id == identity, CourseIndexEntry.assignment_revision == assignment.revision).order_by(CourseIndexEntry.ordinal))).all()
        index_hash = verify_index(assignment, scoped_chunks(canonical_blocks(source.record), assignment.block_ids), entries)
        manifest_items.append({"assignment_id": str(identity), "revision": assignment.revision, "approval_fingerprint": assignment.approval_fingerprint, "index_count": len(entries), "index_hash": index_hash})
    artifacts = []
    for identity in sorted(artifact_ids, key=str):
        artifact = await scoped_row(session, CourseDerivedArtifact, identity, boundary)
        await validate_artifact(session, boundary, artifact, set(map(str, assignment_ids)))
        artifacts.append({"id": str(identity), "fingerprint": artifact_digest(artifact)})
    manifest = {"version": 1, "course_id": str(course_id), "curriculum_id": str(curriculum_id), "assignments": manifest_items, "artifacts": artifacts}
    digest = fingerprint(manifest)
    existing = await session.scalar(select(CourseKnowledgeRelease).where(*boundary.filters(CourseKnowledgeRelease), CourseKnowledgeRelease.course_id == course_id, CourseKnowledgeRelease.curriculum_id == curriculum_id, CourseKnowledgeRelease.manifest_hash == digest))
    if existing:
        return existing
    release = CourseKnowledgeRelease(**boundary.values(), course_id=course_id, curriculum_id=curriculum_id, manifest=manifest, manifest_hash=digest, created_by=reviewer_id, status="candidate")
    session.add(release)
    await session.flush()
    for item in manifest_items:
        session.add(CourseReleaseMember(**boundary.values(), release_id=release.id, assignment_id=UUID(item["assignment_id"]), assignment_revision=item["revision"], approval_fingerprint=item["approval_fingerprint"]))
    await session.flush()
    return release


async def publish_release(session: AsyncSession, boundary: Boundary, release_id: UUID, *, expected_epoch: int) -> CourseReleaseHead:
    release = await scoped_row(session, CourseKnowledgeRelease, release_id, boundary)
    head = await release_head(session, boundary, release.course_id, release.curriculum_id, create=True, lock=True)
    if head is None:
        raise KnowledgePolicyError("The release head is unavailable")
    if head.release_id == release.id and head.epoch == expected_epoch + 1:
        return head
    if head.epoch != expected_epoch:
        raise KnowledgePolicyError("The active release or permissions changed; reload and review before publishing")
    if release.status == "failed" or fingerprint(release.manifest) != release.manifest_hash:
        raise KnowledgePolicyError("The candidate manifest failed its integrity check")
    # Re-run index, approval and dependency checks under the authoritative head lock.
    current = await candidate_release(session, boundary, course_id=release.course_id, curriculum_id=release.curriculum_id,
        assignment_ids=[UUID(i["assignment_id"]) for i in release.manifest["assignments"]],
        artifact_ids=[UUID(i["id"]) for i in release.manifest["artifacts"]], reviewer_id=release.created_by)
    if current.manifest_hash != release.manifest_hash:
        raise KnowledgePolicyError("Candidate content changed; build and review another release")
    release.status = "published"
    release.published_at = datetime.now(UTC)
    head.release_id = release.id
    head.epoch += 1
    await session.flush()
    return head


async def withdraw_assignment(session: AsyncSession, boundary: Boundary, assignment_id: UUID, reason: str) -> CourseMaterialAssignment:
    current = await scoped_row(session, CourseMaterialAssignment, assignment_id, boundary)
    await release_head(session, boundary, current.course_id, current.curriculum_id, lock=True)
    assignment = await scoped_row(session, CourseMaterialAssignment, assignment_id, boundary, lock=True)
    assignment.status = "withdrawn"
    assignment.review_reason = reason
    await invalidate_head(session, boundary, assignment.course_id, assignment.curriculum_id)
    artifacts = (await session.scalars(select(CourseDerivedArtifact).where(*boundary.filters(CourseDerivedArtifact), CourseDerivedArtifact.withdrawn.is_(False)))).all()
    for artifact in artifacts:
        if str(assignment_id) in artifact.assignment_ids:
            artifact.withdrawn = True
    await session.flush()
    return assignment


async def withdraw_source(session: AsyncSession, boundary: Boundary, version_id: UUID, reason: str) -> CourseSourceVersion:
    source = await scoped_row(session, CourseSourceVersion, version_id, boundary, lock=True)
    source.withdrawn = True
    assignments = (await session.scalars(select(CourseMaterialAssignment).where(*boundary.filters(CourseMaterialAssignment), CourseMaterialAssignment.source_version_id == source.id).order_by(CourseMaterialAssignment.course_id, CourseMaterialAssignment.curriculum_id, CourseMaterialAssignment.id))).all()
    for assignment in assignments:
        await withdraw_assignment(session, boundary, assignment.id, reason)
    return source


def artifact_digest(artifact: CourseDerivedArtifact) -> str:
    return fingerprint({"content": artifact.content, "dependencies": artifact.source_fingerprints, "type": artifact.artifact_type, "generation": artifact.generation_configuration_version, "answer_key_validated": artifact.answer_key_validated, "audience": artifact.audience})


async def validate_artifact(session: AsyncSession, boundary: Boundary, artifact: CourseDerivedArtifact, allowed_ids: set[str]) -> list[CourseMaterialAssignment]:
    if artifact.withdrawn or artifact.review_status != "approved" or not set(artifact.assignment_ids) <= allowed_ids:
        raise KnowledgePolicyError("Derived material requires approved, active release dependencies")
    assignments = []
    for identity in artifact.assignment_ids:
        assignment = await scoped_row(session, CourseMaterialAssignment, UUID(identity), boundary)
        source = await scoped_row(session, CourseSourceVersion, assignment.source_version_id, boundary)
        if assignment.status != "approved" or source.withdrawn or artifact.source_fingerprints.get(identity) != assignment_digest(assignment, source):
            raise KnowledgePolicyError("A derived artifact dependency has changed or was withdrawn")
        assignments.append(assignment)
    if asdict(audience_intersection(assignment_audience(a) for a in assignments)) != artifact.audience:
        raise KnowledgePolicyError("The artifact audience differs from its source intersection")
    return assignments


@dataclass(frozen=True, slots=True)
class KnowledgeContext:
    learner: LearnerScope
    release_id: UUID | None
    epoch: int
    context_fingerprint: str
    course_name: str
    curriculum_name: str
    teaching_configuration: dict[str, Any]


async def resolve_context(session: AsyncSession, boundary: Boundary, enrollment_id: UUID, *, expected_student_id: UUID | None = None, expected_course_id: UUID | None = None, expected_batch_id: UUID | None = None, paper_override: UUID | None = None, use_paper_override: bool = False) -> KnowledgeContext:
    from northstar_api.agent_purpose import AgentPurpose, get_agent_purpose
    from northstar_api.education import EducationCourse
    from northstar_api.education_batches import EducationBatch
    from northstar_api.education_enrollments import EducationEnrollment
    from northstar_api.education_students import EducationStudent
    from northstar_api.models import Agent, AgentStatus
    from northstar_api.services.workspace_dates import workspace_today

    agent = await session.scalar(select(Agent).where(Agent.id == boundary.agent_id, Agent.tenant_id == boundary.tenant_id, Agent.workspace_id == boundary.workspace_id).execution_options(populate_existing=True))
    if agent is None or agent.deleted_at is not None or agent.status != AgentStatus.ACTIVE or await get_agent_purpose(session, tenant_id=boundary.tenant_id, workspace_id=boundary.workspace_id, agent_id=boundary.agent_id) is not AgentPurpose.EDUCATION:
        raise KnowledgePolicyError("The selected Education Agent is not active")
    enrollment = await session.scalar(select(EducationEnrollment).where(*boundary.filters(EducationEnrollment), EducationEnrollment.id == enrollment_id, EducationEnrollment.status == "active").execution_options(populate_existing=True))
    if enrollment is None or (expected_student_id is not None and enrollment.student_id != expected_student_id) or (expected_course_id is not None and enrollment.course_id != expected_course_id) or (expected_batch_id is not None and enrollment.batch_id != expected_batch_id):
        raise KnowledgePolicyError("The selected enrollment is no longer authorized")
    student = await session.scalar(select(EducationStudent).where(EducationStudent.id == enrollment.student_id, EducationStudent.tenant_id == boundary.tenant_id, EducationStudent.workspace_id == boundary.workspace_id, EducationStudent.status == "active"))
    course = await session.scalar(select(EducationCourse).where(EducationCourse.id == enrollment.course_id, EducationCourse.tenant_id == boundary.tenant_id, EducationCourse.workspace_id == boundary.workspace_id, EducationCourse.status == "active"))
    batch = await session.scalar(select(EducationBatch).where(EducationBatch.id == enrollment.batch_id, EducationBatch.tenant_id == boundary.tenant_id, EducationBatch.workspace_id == boundary.workspace_id, EducationBatch.course_id == enrollment.course_id, EducationBatch.status == "active"))
    today = await workspace_today(session, tenant_id=boundary.tenant_id, workspace_id=boundary.workspace_id)
    if student is None or course is None or batch is None:
        raise KnowledgePolicyError("The student, course, or batch is inactive")
    for record in (batch, enrollment):
        if (record.starts_on is not None and today < record.starts_on) or (record.ends_on is not None and today > record.ends_on):
            raise KnowledgePolicyError("The selected enrollment or batch is outside its access dates")
    access = await session.scalar(select(CourseEnrollmentAccess).where(*boundary.filters(CourseEnrollmentAccess), CourseEnrollmentAccess.enrollment_id == enrollment_id, CourseEnrollmentAccess.active.is_(True)).execution_options(populate_existing=True))
    if access is None:
        raise KnowledgePolicyError("The institute has not configured curriculum and paper access for this enrollment")
    curriculum = await session.scalar(select(CourseCurriculum).where(CourseCurriculum.id == access.curriculum_id, CourseCurriculum.course_id == enrollment.course_id, CourseCurriculum.tenant_id == boundary.tenant_id, CourseCurriculum.workspace_id == boundary.workspace_id, CourseCurriculum.active.is_(True)))
    binding = await session.scalar(select(CourseBatchCurriculum).where(CourseBatchCurriculum.batch_id == enrollment.batch_id, CourseBatchCurriculum.curriculum_id == access.curriculum_id, CourseBatchCurriculum.tenant_id == boundary.tenant_id, CourseBatchCurriculum.workspace_id == boundary.workspace_id))
    if curriculum is None or binding is None:
        raise KnowledgePolicyError("The enrollment and batch do not have a matching active curriculum")
    paper_ids = frozenset(str(p) for p in (await session.scalars(select(CoursePaper.id).where(CoursePaper.id.in_([UUID(p) for p in access.paper_ids]), CoursePaper.curriculum_id == curriculum.id, CoursePaper.tenant_id == boundary.tenant_id, CoursePaper.workspace_id == boundary.workspace_id, CoursePaper.active.is_(True)))).all())
    selected = paper_override if use_paper_override else access.selected_paper_id
    if selected is not None and str(selected) not in paper_ids:
        raise KnowledgePolicyError("The selected paper is not authorized by this enrollment")
    learner = LearnerScope(str(boundary.tenant_id), str(boundary.workspace_id), str(boundary.agent_id), str(enrollment.student_id), str(enrollment.id), str(enrollment.course_id), str(curriculum.id), str(enrollment.batch_id), paper_ids, str(selected) if selected else None, access.revision)
    head = await release_head(session, boundary, enrollment.course_id, curriculum.id)
    release_id = head.release_id if head else None
    epoch = head.epoch if head else 0
    live_members: list[Any] = []
    live_artifacts: list[Any] = []
    if release_id is not None:
        release = await scoped_row(session, CourseKnowledgeRelease, release_id, boundary)
        if release.status != "published" or release.course_id != enrollment.course_id or release.curriculum_id != curriculum.id:
            raise KnowledgePolicyError("The authoritative course release pointer is invalid")
        # Membership/dependency changes also invalidate prior response history when
        # a legacy source-deletion endpoint cascades rows without touching the head.
        members = (await session.execute(select(
            CourseMaterialAssignment.id, CourseMaterialAssignment.revision,
            CourseMaterialAssignment.status, CourseMaterialAssignment.index_status,
            CourseMaterialAssignment.approval_fingerprint, CourseSourceVersion.id,
            CourseSourceVersion.record_hash, CourseSourceVersion.withdrawn,
        ).join(CourseReleaseMember, CourseReleaseMember.assignment_id == CourseMaterialAssignment.id)
         .join(CourseSourceVersion, CourseSourceVersion.id == CourseMaterialAssignment.source_version_id)
         .where(*boundary.filters(CourseMaterialAssignment), *boundary.filters(CourseReleaseMember),
                *boundary.filters(CourseSourceVersion), CourseReleaseMember.release_id == release_id)
         .order_by(CourseMaterialAssignment.id))).all()
        live_members = [[str(v) if isinstance(v, UUID) else v for v in row] for row in members]
        artifact_ids = [UUID(item["id"]) for item in release.manifest.get("artifacts", [])]
        rows = (await session.execute(select(CourseDerivedArtifact.id, CourseDerivedArtifact.review_status,
            CourseDerivedArtifact.withdrawn, CourseDerivedArtifact.answer_key_validated,
            CourseDerivedArtifact.source_fingerprints).where(*boundary.filters(CourseDerivedArtifact),
            CourseDerivedArtifact.id.in_(artifact_ids)).order_by(CourseDerivedArtifact.id))).all()
        live_artifacts = [[str(v) if isinstance(v, UUID) else v for v in row] for row in rows]
    key = fingerprint({
        **{k: v for k, v in asdict(learner).items() if k != "paper_ids"},
        "paper_ids": sorted(paper_ids), "release_id": str(release_id) if release_id else None,
        "epoch": epoch, "teaching_configuration": curriculum.teaching_configuration,
        "live_members": live_members, "live_artifacts": live_artifacts,
    })
    return KnowledgeContext(learner, release_id, epoch, key, course.name, curriculum.name, curriculum.teaching_configuration)


def authorized_entries(boundary: Boundary, context: KnowledgeContext) -> Any:
    """This same SQL boundary is used by dense/lexical search and excerpt reads."""
    learner = context.learner
    paper_filter = CourseMaterialAssignment.overview.is_(True)
    if learner.selected_paper_id is not None and learner.selected_paper_id in learner.paper_ids:
        paper_filter = or_(paper_filter, CourseMaterialAssignment.paper_id == UUID(learner.selected_paper_id))
    return (
        select(CourseIndexEntry, CourseMaterialAssignment, CourseSourceVersion)
        .join(CourseMaterialAssignment, CourseIndexEntry.assignment_id == CourseMaterialAssignment.id)
        .join(CourseSourceVersion, CourseSourceVersion.id == CourseMaterialAssignment.source_version_id)
        .join(CourseReleaseMember, CourseReleaseMember.assignment_id == CourseMaterialAssignment.id)
        .where(
            *boundary.filters(CourseIndexEntry), *boundary.filters(CourseMaterialAssignment),
            *boundary.filters(CourseSourceVersion), *boundary.filters(CourseReleaseMember),
            CourseReleaseMember.release_id == context.release_id if context.release_id else False,
            CourseMaterialAssignment.course_id == UUID(learner.course_id),
            CourseMaterialAssignment.curriculum_id == UUID(learner.curriculum_id),
            CourseMaterialAssignment.status == "approved", CourseMaterialAssignment.index_status == "ready",
            CourseSourceVersion.withdrawn.is_(False),
            CourseMaterialAssignment.revision == CourseReleaseMember.assignment_revision,
            CourseIndexEntry.assignment_revision == CourseReleaseMember.assignment_revision,
            CourseMaterialAssignment.approval_fingerprint == CourseReleaseMember.approval_fingerprint,
            CourseIndexEntry.approval_fingerprint == CourseReleaseMember.approval_fingerprint,
            or_(CourseMaterialAssignment.batch_id.is_(None), CourseMaterialAssignment.batch_id == UUID(learner.batch_id)),
            paper_filter,
        )
    )


def entry_evidence(entry: CourseIndexEntry, assignment: CourseMaterialAssignment, source: CourseSourceVersion, context: KnowledgeContext, score: float) -> Any:
    from northstar_api.modules.knowledge.retrieval import Evidence

    if entry.content_hash != fingerprint(entry.content) or not set(entry.block_ids) <= set(assignment.block_ids):
        raise KnowledgePolicyError("Retrieved course evidence failed integrity validation")
    return Evidence(
        kind="course_chunk", entity_id=str(entry.id), source_id=str(source.source_id), title=source.title,
        url=None, text=entry.content, score=score,
        metadata={
            "source_version_id": str(source.id), "source_revision": source.source_revision,
            "assignment_id": str(assignment.id), "assignment_revision": assignment.revision,
            "release_id": str(context.release_id), "context_fingerprint": context.context_fingerprint,
            "content_hash": entry.content_hash, "block_ids": entry.block_ids,
            "source_references": entry.source_references,
            "page_number": next((r.get("page_number") for r in entry.source_references if r.get("page_number")), None),
            "chunk_type": "authorized_course_blocks",
        },
    )


async def retrieve_course_evidence(session: AsyncSession, boundary: Boundary, context: KnowledgeContext, query: str, *, model: Any = None, candidate_limit: int = 60, result_limit: int = 8) -> list[Any]:
    import re

    from northstar_api.config import get_settings
    from northstar_api.modules.knowledge.retrieval import _rerank

    if context.release_id is None:
        return []
    settings = get_settings()
    candidate_limit = max(1, min(candidate_limit, 200))
    result_limit = max(1, min(result_limit, 30))
    statement = authorized_entries(boundary, context)
    candidates: dict[str, Any] = {}
    if session.bind is not None and session.bind.dialect.name == "postgresql":
        ts_query = func.websearch_to_tsquery("simple", query)
        rank = func.ts_rank_cd(func.to_tsvector("simple", CourseIndexEntry.content), ts_query)
        lexical = (await session.execute(statement.add_columns(rank.label("rank")).where(ts_query.op("@@")(func.to_tsvector("simple", CourseIndexEntry.content))).order_by(rank.desc()).limit(candidate_limit))).all()
        for entry, assignment, source, raw_score in lexical:
            evidence = entry_evidence(entry, assignment, source, context, min(1.0, float(raw_score)))
            candidates[evidence.entity_id] = evidence
    else:
        # SQLite development fallback never loads another audience's content.
        rows = (await session.execute(statement.order_by(CourseIndexEntry.id).limit(5000))).all()
        terms = set(re.findall(r"\w+", query.casefold()))
        for entry, assignment, source in rows:
            words = set(re.findall(r"\w+", entry.content.casefold()))
            score = len(terms & words) / max(1, len(terms | words))
            candidates[str(entry.id)] = entry_evidence(entry, assignment, source, context, score)
    evidence = [e for e in candidates.values() if e.score >= settings.retrieval_min_score]
    # Only published, reviewed artifacts with ALL dependencies currently allowed.
    release = await scoped_row(session, CourseKnowledgeRelease, context.release_id, boundary)
    allowed = {str(identity) for identity in (await session.scalars(statement.with_only_columns(CourseMaterialAssignment.id, maintain_column_froms=True).distinct())).all()}
    artifact_manifest = {item["id"]: item for item in release.manifest.get("artifacts", [])}
    # Read permission metadata before fetching any generated private content.
    artifact_metadata = (await session.execute(select(CourseDerivedArtifact.id,
        CourseDerivedArtifact.assignment_ids, CourseDerivedArtifact.audience).where(
        *boundary.filters(CourseDerivedArtifact), CourseDerivedArtifact.id.in_([UUID(k) for k in artifact_manifest]),
        CourseDerivedArtifact.review_status == "approved", CourseDerivedArtifact.withdrawn.is_(False),
    ))).all()
    permitted_artifacts = [identity for identity, dependencies, audience in artifact_metadata
        if dependencies and set(dependencies) <= allowed and context.learner.permits(Audience(**audience))]
    for identity in permitted_artifacts:
        item = artifact_manifest[str(identity)]
        artifact = await scoped_row(session, CourseDerivedArtifact, identity, boundary)
        try:
            await validate_artifact(session, boundary, artifact, allowed)
        except KnowledgePolicyError:
            continue
        if artifact_digest(artifact) != item["fingerprint"]:
            continue
        terms = set(re.findall(r"\w+", query.casefold()))
        words = set(re.findall(r"\w+", artifact.content.casefold()))
        score = len(terms & words) / max(1, len(terms | words))
        if score >= settings.retrieval_min_score:
            from northstar_api.modules.knowledge.retrieval import Evidence
            evidence.append(Evidence("course_artifact", str(artifact.id), None, f"Teacher-reviewed {artifact.artifact_type}", None, artifact.content, score, {"context_fingerprint": context.context_fingerprint, "release_id": str(context.release_id), "artifact_fingerprint": artifact_digest(artifact), "assignment_ids": artifact.assignment_ids, "source_version_ids": artifact.source_version_ids, "source_block_ids": artifact.source_block_ids, "answer_key_validated": artifact.answer_key_validated}))
    return _rerank(evidence, query, result_limit)


async def revalidate_evidence(session: AsyncSession, boundary: Boundary, context: KnowledgeContext, evidence: list[Any], *, use_paper_override: bool = False) -> None:
    """Check immediately before persistence/replay; never rely on a cached grant."""
    fresh = await resolve_context(session, boundary, UUID(context.learner.enrollment_id), expected_student_id=UUID(context.learner.student_id), expected_course_id=UUID(context.learner.course_id), expected_batch_id=UUID(context.learner.batch_id), paper_override=UUID(context.learner.selected_paper_id) if context.learner.selected_paper_id else None, use_paper_override=use_paper_override)
    if fresh.context_fingerprint != context.context_fingerprint:
        raise KnowledgePolicyError("Course knowledge or access changed while answering; retry the question")
    statement = authorized_entries(boundary, fresh)
    for item in evidence:
        if item.kind == "course_chunk":
            row = (await session.execute(statement.where(CourseIndexEntry.id == UUID(item.entity_id)))).first()
            if row is None or row[0].content_hash != item.metadata.get("content_hash"):
                raise KnowledgePolicyError("A cited source was withdrawn or changed")
        elif item.kind == "course_artifact":
            artifact = await scoped_row(session, CourseDerivedArtifact, UUID(item.entity_id), boundary)
            allowed = {str(identity) for identity in (await session.scalars(statement.with_only_columns(CourseMaterialAssignment.id, maintain_column_froms=True).distinct())).all()}
            await validate_artifact(session, boundary, artifact, allowed)
            if artifact_digest(artifact) != item.metadata.get("artifact_fingerprint"):
                raise KnowledgePolicyError("A derived artifact changed while answering")
        elif item.source_id is not None or item.kind in {"fact", "chunk"}:
                raise KnowledgePolicyError("Unscoped private evidence cannot enter an Education answer")
