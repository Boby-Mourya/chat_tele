from __future__ import annotations

import hashlib
import zipfile
from datetime import UTC, datetime
from typing import Annotated, Literal
from urllib.parse import urlsplit
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import Field
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.config import get_settings
from northstar_api.database import get_session
from northstar_api.dependencies import require_permissions
from northstar_api.education_knowledge_lifecycle import (
    EducationDerivedLearningArtifact,
    EducationKnowledgeRelease,
    EducationReleaseAssignment,
    EducationSourceVersion,
)
from northstar_api.education_knowledge_schemas import (
    EducationKnowledgeScopeOut,
    EducationKnowledgeScopeRef,
    EducationKnowledgeScopeReplace,
)
from northstar_api.education_knowledge_scope import EducationKnowledgeScope
from northstar_api.education_release_schemas import (
    EducationReleaseActivate,
    EducationReleaseCreate,
    EducationReleaseOut,
)
from northstar_api.models import (
    FactStatus,
    IngestionJob,
    JobStatus,
    KnowledgeFact,
    KnowledgeKind,
    KnowledgeSource,
    KnowledgeStatus,
)
from northstar_api.modules.knowledge.ingestion import ingest_source_async
from northstar_api.routers.agents import scoped_agent
from northstar_api.schemas import (
    APIModel,
    FactCreate,
    FactOut,
    FactPatch,
    JobOut,
    KnowledgeCreate,
    KnowledgeOut,
    KnowledgeUntrain,
    UploadPresignOut,
    UploadPresignRequest,
)
from northstar_api.security import Principal
from northstar_api.services.education_knowledge import (
    list_fact_scopes,
    list_source_scopes,
    replace_fact_scopes,
    replace_source_scopes,
    require_education_agent,
    validate_scope_pairs,
)
from northstar_api.services.extraction_review import apply_review
from northstar_api.services.extraction_schema import Reading
from northstar_api.services.hybrid_extraction import ExtractionPackage
from northstar_api.services.llm import nvidia_adapter
from northstar_api.services.object_store import InvalidUpload, ObjectStoreUnavailable, object_store
from northstar_api.services.outbox import enqueue_event

router = APIRouter(tags=["knowledge"])
DB = Annotated[AsyncSession, Depends(get_session)]
KnowledgeViewPrincipal = Annotated[Principal, Depends(require_permissions("knowledge.view"))]
KnowledgeManagePrincipal = Annotated[Principal, Depends(require_permissions("knowledge.manage"))]
logger = structlog.get_logger(__name__)


@router.post("/uploads/presign", response_model=UploadPresignOut)
async def presign_upload(
    payload: UploadPresignRequest, principal: KnowledgeManagePrincipal
) -> UploadPresignOut:
    settings = get_settings()
    if payload.size_bytes > settings.upload_max_bytes:
        limit_mb = settings.upload_max_bytes / (1024 * 1024)
        raise HTTPException(status_code=413, detail=f"Files must be {limit_mb:g} MB or smaller.")
    try:
        key, url, fields, expires_at = await object_store.presign_post(
            tenant_id=principal.tenant_id,
            filename=payload.filename,
            content_type=payload.content_type,
            size_bytes=payload.size_bytes,
            checksum_sha256=payload.checksum_sha256,
        )
    except InvalidUpload as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except ObjectStoreUnavailable:
        raise HTTPException(status_code=503, detail="Object storage is not configured") from None
    public_endpoint = urlsplit(settings.s3_public_endpoint_url or "")
    if public_endpoint.hostname in {"localhost", "127.0.0.1"}:
        signed_path = urlsplit(url).path
        if not signed_path.startswith(f"/{settings.s3_bucket}"):
            raise HTTPException(status_code=503, detail="Object storage returned an invalid upload path")
        url = f"/storage{signed_path}"
    return UploadPresignOut(url=url, object_key=key, fields=fields, expires_at=expires_at)


def source_response(source: KnowledgeSource) -> KnowledgeOut:
    return KnowledgeOut(
        id=source.id,
        workspace_id=source.workspace_id,
        agent_id=source.agent_id,
        name=source.name,
        kind=source.kind,
        status=source.status,
        size_label=source.size_label,
        chunks=source.chunk_count,
        updated_at=source.updated_at,
        url=source.url,
        content=source.content if source.kind == KnowledgeKind.TEXT else None,
        error=source.error,
        extraction_issue_count=source.extraction_issue_count,
        extraction_available=bool(source.extraction_key),
    )


@router.get("/agents/{agent_id}/knowledge", response_model=list[KnowledgeOut])
async def list_knowledge(
    agent_id: UUID, principal: KnowledgeViewPrincipal, session: DB
) -> list[KnowledgeOut]:
    await scoped_agent(
        session, principal.tenant_id, agent_id,
        workspace_id=principal.workspace_id, allowed_agent_ids=principal.agent_ids,
    )
    sources = (
        await session.scalars(
            select(KnowledgeSource)
            .where(
                KnowledgeSource.tenant_id == principal.tenant_id,
                KnowledgeSource.workspace_id == principal.workspace_id,
                KnowledgeSource.agent_id == agent_id,
            )
            .order_by(KnowledgeSource.updated_at.desc())
        )
    ).all()
    return [source_response(item) for item in sources]


@router.post("/agents/{agent_id}/knowledge", response_model=KnowledgeOut, status_code=201)
async def add_knowledge(
    agent_id: UUID, payload: KnowledgeCreate, principal: KnowledgeManagePrincipal, session: DB
) -> KnowledgeOut:
    agent = await scoped_agent(
        session, principal.tenant_id, agent_id,
        workspace_id=principal.workspace_id, allowed_agent_ids=principal.agent_ids,
    )
    if payload.kind == KnowledgeKind.TEXT and not payload.content:
        raise HTTPException(status_code=422, detail="Text sources require content")
    if payload.kind in (KnowledgeKind.URL, KnowledgeKind.SITEMAP) and not payload.url:
        raise HTTPException(status_code=422, detail="URL and sitemap sources require a URL")
    if payload.kind == KnowledgeKind.FILE and not payload.object_key:
        raise HTTPException(status_code=422, detail="File sources require an uploaded object key")
    if payload.kind == KnowledgeKind.FILE and payload.content is not None:
        raise HTTPException(status_code=422, detail="Uploaded files must pass source extraction and review")
    if payload.object_key and payload.kind != KnowledgeKind.FILE:
        raise HTTPException(status_code=422, detail="Only file sources can reference an uploaded object")
    if payload.education_destination is not None and payload.unassigned_inbox:
        raise HTTPException(status_code=422, detail="Choose an Education destination or the unassigned inbox")
    if payload.education_destination is not None:
        await require_education_agent(
            session,
            tenant_id=principal.tenant_id,
            workspace_id=principal.workspace_id,
            agent=agent,
        )

    object_key = payload.object_key
    uploaded_checksum: str | None = None
    uploaded_size: int | None = None
    if object_key:
        try:
            object_key, uploaded_checksum, uploaded_size = await object_store.promote_staged(
                principal.tenant_id, object_key
            )
        except InvalidUpload as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        except ObjectStoreUnavailable:
            raise HTTPException(status_code=503, detail="Object storage is unavailable") from None

    raw_identity = payload.content or str(payload.url or object_key)
    source = KnowledgeSource(
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        agent_id=agent_id,
        name=payload.name.strip(),
        kind=payload.kind,
        status=KnowledgeStatus.PROCESSING,
        size_label=_size_label(uploaded_size) if uploaded_size is not None else "Queued",
        url=str(payload.url) if payload.url else None,
        content=payload.content,
        object_key=object_key,
        checksum=uploaded_checksum or hashlib.sha256(raw_identity.encode()).hexdigest(),
    )
    session.add(source)
    await session.flush()
    source_version = EducationSourceVersion(
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        source_id=source.id,
        version=source.revision,
        checksum=source.checksum or "",
        processing_configuration={"pipeline": "existing", "sourceKind": source.kind.value},
        state="processing",
    )
    session.add(source_version)
    await session.flush()
    if payload.education_destination is not None:
        destination = payload.education_destination
        normalized = await validate_scope_pairs(
            session,
            tenant_id=principal.tenant_id,
            workspace_id=principal.workspace_id,
            pairs=[
                EducationKnowledgeScopeRef(
                    course_id=destination.course_id,
                    curriculum_id=destination.curriculum_id,
                    paper_id=destination.paper_id,
                    batch_id=destination.batch_id,
                    material_type=destination.material_type,
                )
            ],
        )
        selected = normalized[0]
        session.add(
            EducationKnowledgeScope(
                tenant_id=principal.tenant_id,
                workspace_id=principal.workspace_id,
                agent_id=agent.id,
                source_id=source.id,
                source_version_id=source_version.id,
                course_id=selected.course_id,
                curriculum_id=selected.curriculum_id,
                paper_id=selected.paper_id,
                batch_id=selected.batch_id,
                material_type=selected.material_type,
                approval_status="draft",
                requires_release=True,
            )
        )
    job = IngestionJob(
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        source_id=source.id,
        status=JobStatus.QUEUED,
        idempotency_key=f"ingest:{source.id}:{source.revision}:{source.checksum}",
    )
    session.add(job)
    enqueue_event(
        session,
        tenant_id=principal.tenant_id,
        aggregate_type="knowledge_source",
        aggregate_id=source.id,
        event_type="knowledge.source.created.v1",
        payload={"sourceId": str(source.id), "agentId": str(agent_id), "kind": source.kind.value},
    )
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        if object_key:
            try:
                await object_store.purge_exact(object_key)
            except Exception as cleanup_error:
                logger.warning(
                    "promoted_upload_cleanup_failed",
                    object_key=object_key,
                    error=type(cleanup_error).__name__,
                )
        raise

    settings = get_settings()
    if not settings.background_dispatch_enabled:
        await ingest_source_async(session, source.id)
        await session.refresh(source)
    return source_response(source)


async def _scoped_source(
    source_id: UUID,
    *,
    principal: Principal,
    session: AsyncSession,
) -> KnowledgeSource:
    source = await session.scalar(
        select(KnowledgeSource).where(
            KnowledgeSource.id == source_id,
            KnowledgeSource.tenant_id == principal.tenant_id,
            KnowledgeSource.workspace_id == principal.workspace_id,
        )
    )
    if source is None:
        raise HTTPException(status_code=404, detail="Knowledge source not found")
    agent = await scoped_agent(
        session,
        principal.tenant_id,
        source.agent_id,
        workspace_id=principal.workspace_id,
        allowed_agent_ids=principal.agent_ids,
    )
    await require_education_agent(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        agent=agent,
    )
    return source


async def _review_source(source_id: UUID, principal: Principal, session: AsyncSession) -> KnowledgeSource:
    source = await session.scalar(
        select(KnowledgeSource)
        .with_for_update()
        .where(
            KnowledgeSource.id == source_id,
            KnowledgeSource.tenant_id == principal.tenant_id,
            KnowledgeSource.workspace_id == principal.workspace_id,
        )
    )
    if source is None:
        raise HTTPException(status_code=404, detail="Knowledge source not found")
    await scoped_agent(
        session, principal.tenant_id, source.agent_id,
        workspace_id=principal.workspace_id, allowed_agent_ids=principal.agent_ids,
    )
    return source


async def _load_extraction(source: KnowledgeSource) -> ExtractionPackage:
    if not source.extraction_key or not source.extraction_key.startswith(
        f"extractions/{source.tenant_id}/{source.id}/"
    ):
        raise HTTPException(status_code=404, detail="Extraction evidence is not available")
    blob, _ = await object_store.download(source.extraction_key, limit_bytes=1024 * 1024 * 1024)
    try:
        return ExtractionPackage.from_archive(blob, source_sha256=source.checksum, revision=source.revision)
    except (ValueError, KeyError, TypeError, zipfile.BadZipFile):
        raise HTTPException(status_code=409, detail="Extraction evidence is invalid or changed") from None


@router.get("/knowledge/{source_id}/extraction")
async def get_extraction(
    source_id: UUID, principal: KnowledgeViewPrincipal, session: DB
) -> dict[str, object]:
    source = await _review_source(source_id, principal, session)
    return (await _load_extraction(source)).record


@router.get("/knowledge/{source_id}/extraction/source-pdf")
async def get_extraction_source_pdf(
    source_id: UUID, principal: KnowledgeViewPrincipal, session: DB
) -> Response:
    """Open the immutable PDF bytes that were used for this extraction revision."""
    source = await _review_source(source_id, principal, session)
    package = await _load_extraction(source)
    original = package.images.get("source/original.pdf")
    if original is None:
        raise HTTPException(status_code=404, detail="The stored source is not a PDF")
    safe_name = source.name.replace('"', "") or "source.pdf"
    return Response(
        content=original,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{safe_name}"'},
    )


@router.get("/knowledge/{source_id}/extraction/text")
async def get_extraction_text(
    source_id: UUID, principal: KnowledgeViewPrincipal, session: DB
) -> Response:
    """Download the canonical extracted text and structured review record."""
    source = await _review_source(source_id, principal, session)
    safe_name = source.name.replace('"', "") or "source"
    return Response(
        content=(await _load_extraction(source)).review_text(),
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}-extracted.txt"'},
    )


@router.get("/knowledge/{source_id}/extraction/pages/{page_number}")
async def get_extraction_page(
    source_id: UUID, page_number: int, principal: KnowledgeViewPrincipal, session: DB
) -> Response:
    source = await _review_source(source_id, principal, session)
    package = await _load_extraction(source)
    path = f"pages/page_{page_number:04d}.png"
    if path not in package.images:
        raise HTTPException(status_code=404, detail="Page image not found")
    return Response(content=package.images[path], media_type="image/png")


@router.get("/knowledge/{source_id}/extraction/regions/{block_id}")
async def get_extraction_region(
    source_id: UUID,
    block_id: str,
    principal: KnowledgeViewPrincipal,
    session: DB,
) -> Response:
    source = await _review_source(source_id, principal, session)
    package = await _load_extraction(source)
    block = next(
        (b for p in package.record["pages"] for b in p.get("blocks", []) if b["id"] == block_id), None
    )
    if not block or block.get("crop") not in package.images:
        raise HTTPException(status_code=404, detail="Source region not found")
    return Response(content=package.images[block["crop"]], media_type="image/png")


@router.get("/knowledge/{source_id}/extraction/report")
async def get_extraction_report(source_id: UUID, principal: KnowledgeViewPrincipal, session: DB) -> Response:
    source = await _review_source(source_id, principal, session)
    return Response(content=(await _load_extraction(source)).validation_text(), media_type="text/plain")


@router.get("/knowledge/{source_id}/extraction/archive")
async def get_extraction_archive(source_id: UUID, principal: KnowledgeViewPrincipal, session: DB) -> Response:
    source = await _review_source(source_id, principal, session)
    package = await _load_extraction(source)
    return Response(
        content=package.archive(),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="extraction-review.zip"'},
    )


class ReviewedBlock(APIModel):
    id: str = Field(max_length=100)
    selected_text: str = Field(max_length=200_000)
    structure: Reading | None = None
    related_block_ids: list[str] = Field(default_factory=list, max_length=100)


class ReviewedPage(APIModel):
    number: int = Field(ge=1)
    selected_text: str = Field(max_length=200_000)
    reason: str = Field(min_length=1, max_length=500)
    structure_confirmed: bool = False
    blank_confirmed: bool = False
    blocks: list[ReviewedBlock] = Field(default_factory=list, max_length=1000)


class IssueResolution(APIModel):
    id: str = Field(max_length=100)
    action: Literal["source_verified", "source_anomaly", "unresolved"]
    reason: str = Field(min_length=1, max_length=1000)


class ExtractionApproval(APIModel):
    extraction_revision: int = Field(ge=1)
    pages: list[ReviewedPage] = Field(min_length=1, max_length=5_000)
    issue_resolutions: list[IssueResolution] = Field(default_factory=list, max_length=20000)


@router.post("/knowledge/{source_id}/extraction/retry", response_model=KnowledgeOut)
async def retry_extraction(source_id: UUID, principal: KnowledgeManagePrincipal, session: DB) -> KnowledgeOut:
    source = await _review_source(source_id, principal, session)
    if source.status != KnowledgeStatus.NEEDS_REVIEW or not source.object_key:
        raise HTTPException(status_code=409, detail="Source is not awaiting extraction review")
    source.revision += 1
    source.status = KnowledgeStatus.PROCESSING
    source.error = None
    session.add(
        IngestionJob(
            tenant_id=source.tenant_id,
            workspace_id=source.workspace_id,
            source_id=source.id,
            status=JobStatus.QUEUED,
            idempotency_key=f"ingest:{source.id}:{source.revision}:{source.checksum}",
        )
    )
    enqueue_event(
        session,
        tenant_id=source.tenant_id,
        aggregate_type="knowledge_source",
        aggregate_id=source.id,
        event_type="knowledge.source.created.v1",
        payload={"sourceId": str(source.id), "agentId": str(source.agent_id), "kind": source.kind.value},
    )
    await session.commit()
    if not get_settings().background_dispatch_enabled:
        await ingest_source_async(session, source.id)
        await session.refresh(source)
    return source_response(source)


@router.post("/knowledge/{source_id}/extraction/approve", response_model=KnowledgeOut)
async def approve_extraction(
    source_id: UUID, payload: ExtractionApproval, principal: KnowledgeManagePrincipal, session: DB
) -> KnowledgeOut:
    source = await _review_source(source_id, principal, session)
    if source.status != KnowledgeStatus.NEEDS_REVIEW:
        raise HTTPException(status_code=409, detail="Source is not awaiting extraction review")
    package = await _load_extraction(source)
    if payload.extraction_revision != source.revision:
        raise HTTPException(status_code=409, detail="Evidence changed; reload before reviewing")
    settings = get_settings()
    if sum(len(item.selected_text) for item in payload.pages) > settings.knowledge_max_extracted_characters:
        raise HTTPException(status_code=413, detail="Reviewed text exceeds the extraction limit")
    try:
        apply_review(
            package.record,
            [p.model_dump() for p in payload.pages],
            [r.model_dump() for r in payload.issue_resolutions],
            str(principal.user_id),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    package.refresh()
    pages = package.record["pages"]
    released = package.record["release_eligible"]
    package.record["review_status"] = "verified_release" if released else "needs_review"
    selected = [page["selected_text"] for page in pages]
    # Persist the reviewed evidence before scheduling indexing.
    next_revision = source.revision + 1
    package.record["extraction_revision"] = next_revision
    source.extraction_key = await object_store.put_extraction(
        source.tenant_id, source.id, package.archive(), version=next_revision
    )
    source.revision = next_revision
    source.extraction_issue_count = sum(i.get("status") != "resolved" for i in package.issues)
    if not released:
        source.status = KnowledgeStatus.NEEDS_REVIEW
        await session.commit()
        return source_response(source)
    source.content = "\n\n".join(
        f"===PDF_PAGE:{page['number']}===\n{value}" if page.get("source_unit") == "pdf_page" else value
        for page, value in zip(pages, selected, strict=True)
    )
    source.extraction_issue_count = 0
    source.status = KnowledgeStatus.PROCESSING
    source.revision = next_revision
    job = IngestionJob(
        tenant_id=source.tenant_id,
        workspace_id=source.workspace_id,
        source_id=source.id,
        status=JobStatus.QUEUED,
        idempotency_key=f"ingest:{source.id}:{source.revision}:{source.checksum}",
    )
    session.add(job)
    enqueue_event(
        session,
        tenant_id=source.tenant_id,
        aggregate_type="knowledge_source",
        aggregate_id=source.id,
        event_type="knowledge.source.created.v1",
        payload={"sourceId": str(source.id), "agentId": str(source.agent_id), "kind": source.kind.value},
    )
    await session.commit()
    if not settings.background_dispatch_enabled:
        await ingest_source_async(session, source.id)
        await session.refresh(source)
    return source_response(source)


@router.get(
    "/knowledge/{source_id}/education-scopes",
    response_model=list[EducationKnowledgeScopeOut],
)
async def get_source_education_scopes(
    source_id: UUID,
    principal: KnowledgeViewPrincipal,
    session: DB,
) -> list[EducationKnowledgeScopeOut]:
    source = await _scoped_source(source_id, principal=principal, session=session)
    return list(
        await list_source_scopes(
            session,
            tenant_id=principal.tenant_id,
            workspace_id=principal.workspace_id,
            agent_id=source.agent_id,
            source_id=source.id,
        )
    )


@router.put(
    "/knowledge/{source_id}/education-scopes",
    response_model=list[EducationKnowledgeScopeOut],
)
async def set_source_education_scopes(
    source_id: UUID,
    payload: EducationKnowledgeScopeReplace,
    principal: KnowledgeManagePrincipal,
    session: DB,
) -> list[EducationKnowledgeScopeOut]:
    source = await _scoped_source(source_id, principal=principal, session=session)
    scopes = await replace_source_scopes(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        agent_id=source.agent_id,
        source_id=source.id,
        pairs=payload.scopes,
    )
    enqueue_event(
        session,
        tenant_id=principal.tenant_id,
        aggregate_type="knowledge_source",
        aggregate_id=source.id,
        event_type="education.knowledge.scope.updated.v1",
        payload={
            "sourceId": str(source.id),
            "agentId": str(source.agent_id),
            "scopes": [{"courseId": str(item.course_id), "batchId": str(item.batch_id)} for item in scopes],
        },
    )
    await session.commit()
    return list(scopes)


class EducationMaterialApproval(APIModel):
    extraction_revision: int = Field(ge=1)
    mapping_revision: int = Field(ge=1)


async def _scoped_assignment(
    assignment_id: UUID, *, principal: Principal, session: AsyncSession, lock: bool = False
) -> EducationKnowledgeScope:
    query = select(EducationKnowledgeScope).where(
        EducationKnowledgeScope.id == assignment_id,
        EducationKnowledgeScope.tenant_id == principal.tenant_id,
        EducationKnowledgeScope.workspace_id == principal.workspace_id,
    )
    assignment = await session.scalar(query.with_for_update() if lock else query)
    if assignment is None:
        raise HTTPException(status_code=404, detail="Education material assignment not found")
    return assignment


@router.post(
    "/knowledge/education-assignments/{assignment_id}/approve",
    response_model=EducationKnowledgeScopeOut,
)
async def approve_education_assignment(
    assignment_id: UUID,
    payload: EducationMaterialApproval,
    principal: KnowledgeManagePrincipal,
    session: DB,
) -> EducationKnowledgeScopeOut:
    assignment = await _scoped_assignment(assignment_id, principal=principal, session=session, lock=True)
    if assignment.withdrawn_at is not None:
        raise HTTPException(status_code=409, detail="Withdrawn material cannot be approved")
    if (
        assignment.extraction_revision != payload.extraction_revision
        or assignment.mapping_revision != payload.mapping_revision
    ):
        raise HTTPException(status_code=409, detail="Content or mapping changed; review the latest revision")
    assignment.approval_status = "approved"
    assignment.approved_by = principal.user_id
    assignment.approved_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(assignment)
    return EducationKnowledgeScopeOut.model_validate(assignment)


@router.post(
    "/knowledge/education-assignments/{assignment_id}/publish",
    response_model=EducationKnowledgeScopeOut,
)
async def publish_education_assignment(
    assignment_id: UUID,
    payload: EducationMaterialApproval,
    principal: KnowledgeManagePrincipal,
    session: DB,
) -> EducationKnowledgeScopeOut:
    assignment = await _scoped_assignment(assignment_id, principal=principal, session=session, lock=True)
    if assignment.approval_status != "approved":
        raise HTTPException(status_code=409, detail="Material must be approved before publication")
    if (
        assignment.extraction_revision != payload.extraction_revision
        or assignment.mapping_revision != payload.mapping_revision
    ):
        raise HTTPException(status_code=409, detail="Content or mapping changed; approval is no longer valid")
    if assignment.source_id is not None:
        source = await session.scalar(
            select(KnowledgeSource).where(
                KnowledgeSource.id == assignment.source_id,
                KnowledgeSource.status == KnowledgeStatus.READY,
            )
        )
        if source is None:
            raise HTTPException(status_code=409, detail="Source processing and indexing are not complete")
    assignment.approval_status = "published"
    assignment.published_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(assignment)
    return EducationKnowledgeScopeOut.model_validate(assignment)


@router.post(
    "/knowledge/education-assignments/{assignment_id}/withdraw",
    response_model=EducationKnowledgeScopeOut,
)
async def withdraw_education_assignment(
    assignment_id: UUID,
    principal: KnowledgeManagePrincipal,
    session: DB,
) -> EducationKnowledgeScopeOut:
    assignment = await _scoped_assignment(assignment_id, principal=principal, session=session, lock=True)
    assignment.approval_status = "withdrawn"
    assignment.withdrawn_at = datetime.now(UTC)
    artifacts = (
        await session.scalars(
            select(EducationDerivedLearningArtifact).where(
                EducationDerivedLearningArtifact.tenant_id == principal.tenant_id,
                EducationDerivedLearningArtifact.workspace_id == principal.workspace_id,
                EducationDerivedLearningArtifact.agent_id == assignment.agent_id,
                EducationDerivedLearningArtifact.publication_status != "withdrawn",
            )
        )
    ).all()
    assignment_key = str(assignment.id)
    for artifact in artifacts:
        if assignment_key in artifact.course_assignment_ids:
            artifact.publication_status = "withdrawn"
    await session.commit()
    await session.refresh(assignment)
    return EducationKnowledgeScopeOut.model_validate(assignment)


@router.post(
    "/education/knowledge/releases",
    response_model=EducationReleaseOut,
    status_code=201,
)
async def create_education_release(
    payload: EducationReleaseCreate,
    principal: KnowledgeManagePrincipal,
    session: DB,
) -> EducationReleaseOut:
    if len(set(payload.assignment_ids)) != len(payload.assignment_ids):
        raise HTTPException(status_code=422, detail="Release assignments must be unique")
    assignments = (
        await session.scalars(
            select(EducationKnowledgeScope).where(
                EducationKnowledgeScope.id.in_(payload.assignment_ids),
                EducationKnowledgeScope.tenant_id == principal.tenant_id,
                EducationKnowledgeScope.workspace_id == principal.workspace_id,
            )
        )
    ).all()
    if len(assignments) != len(payload.assignment_ids):
        raise HTTPException(status_code=422, detail="One or more assignments are unavailable")
    if any(
        item.agent_id != payload.agent_id
        or item.course_id != payload.course_id
        or item.curriculum_id != payload.curriculum_id
        for item in assignments
    ):
        raise HTTPException(status_code=422, detail="Every assignment must match the release tuple")
    if any(
        item.approval_status not in {"approved", "published"} or item.withdrawn_at is not None
        for item in assignments
    ):
        raise HTTPException(status_code=409, detail="Every release assignment must be approved and active")

    latest = await session.scalar(
        select(func.max(EducationKnowledgeRelease.revision)).where(
            EducationKnowledgeRelease.tenant_id == principal.tenant_id,
            EducationKnowledgeRelease.workspace_id == principal.workspace_id,
            EducationKnowledgeRelease.agent_id == payload.agent_id,
            EducationKnowledgeRelease.course_id == payload.course_id,
            EducationKnowledgeRelease.curriculum_id == payload.curriculum_id,
        )
    )
    release = EducationKnowledgeRelease(
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        agent_id=payload.agent_id,
        course_id=payload.course_id,
        curriculum_id=payload.curriculum_id,
        revision=int(latest or 0) + 1,
        status="candidate",
        manifest={
            "assignments": [
                {"id": str(item.id), "revision": item.assignment_revision} for item in assignments
            ]
        },
    )
    session.add(release)
    await session.flush()
    session.add_all(
        EducationReleaseAssignment(
            release_id=release.id,
            assignment_id=item.id,
            assignment_revision=item.assignment_revision,
        )
        for item in assignments
    )
    await session.commit()
    await session.refresh(release)
    return EducationReleaseOut.model_validate(release)


@router.post(
    "/education/knowledge/releases/{release_id}/activate",
    response_model=EducationReleaseOut,
)
async def activate_education_release(
    release_id: UUID,
    payload: EducationReleaseActivate,
    principal: KnowledgeManagePrincipal,
    session: DB,
) -> EducationReleaseOut:
    release = await session.scalar(
        select(EducationKnowledgeRelease)
        .with_for_update()
        .where(
            EducationKnowledgeRelease.id == release_id,
            EducationKnowledgeRelease.tenant_id == principal.tenant_id,
            EducationKnowledgeRelease.workspace_id == principal.workspace_id,
        )
    )
    if release is None:
        raise HTTPException(status_code=404, detail="Knowledge release not found")
    if release.status != "candidate":
        raise HTTPException(status_code=409, detail="Only a candidate release can be activated")
    if not payload.index_verified:
        raise HTTPException(status_code=409, detail="Index verification must pass before activation")
    members = (
        await session.execute(
            select(EducationReleaseAssignment, EducationKnowledgeScope)
            .join(
                EducationKnowledgeScope,
                EducationKnowledgeScope.id == EducationReleaseAssignment.assignment_id,
            )
            .where(EducationReleaseAssignment.release_id == release.id)
        )
    ).all()
    if not members or any(
        assignment.approval_status not in {"approved", "published"}
        or assignment.withdrawn_at is not None
        or assignment.assignment_revision != membership.assignment_revision
        for membership, assignment in members
    ):
        raise HTTPException(status_code=409, detail="Release contents changed or are no longer approved")

    await session.execute(
        update(EducationKnowledgeRelease)
        .where(
            EducationKnowledgeRelease.id != release.id,
            EducationKnowledgeRelease.tenant_id == release.tenant_id,
            EducationKnowledgeRelease.workspace_id == release.workspace_id,
            EducationKnowledgeRelease.agent_id == release.agent_id,
            EducationKnowledgeRelease.course_id == release.course_id,
            EducationKnowledgeRelease.curriculum_id == release.curriculum_id,
            EducationKnowledgeRelease.status == "active",
        )
        .values(status="superseded")
    )
    now = datetime.now(UTC)
    for _, assignment in members:
        assignment.approval_status = "published"
        assignment.published_at = now
    release.status = "active"
    release.index_verified = True
    release.activated_by = principal.user_id
    release.activated_at = now
    await session.commit()
    await session.refresh(release)
    return EducationReleaseOut.model_validate(release)


@router.post("/knowledge/untrain")
async def untrain_knowledge(
    payload: KnowledgeUntrain, principal: KnowledgeManagePrincipal, session: DB
) -> dict[str, int]:
    sources = list(
        await session.scalars(
            select(KnowledgeSource).where(
                KnowledgeSource.id.in_(payload.source_ids),
                KnowledgeSource.tenant_id == principal.tenant_id,
                KnowledgeSource.workspace_id == principal.workspace_id,
            )
        )
    )
    if len(sources) != len(payload.source_ids):
        raise HTTPException(status_code=404, detail="One or more knowledge sources were not found")
    removed_chunks = sum(source.chunk_count for source in sources)
    for source in sources:
        await session.delete(source)
        enqueue_event(
            session,
            tenant_id=principal.tenant_id,
            aggregate_type="knowledge_source",
            aggregate_id=source.id,
            event_type="knowledge.source.deleted.v1",
            payload={
                "sourceId": str(source.id),
                "agentId": str(source.agent_id),
                "objectKey": source.object_key,
                "extractionKey": source.extraction_key,
            },
        )
    await session.commit()
    return {"removedSources": len(sources), "removedChunks": removed_chunks}


@router.delete("/knowledge/{source_id}", status_code=204)
async def delete_knowledge(source_id: UUID, principal: KnowledgeManagePrincipal, session: DB) -> Response:
    source = await session.scalar(
        select(KnowledgeSource).where(
            KnowledgeSource.id == source_id,
            KnowledgeSource.tenant_id == principal.tenant_id,
            KnowledgeSource.workspace_id == principal.workspace_id,
        )
    )
    if not source:
        raise HTTPException(status_code=404, detail="Knowledge source not found")
    object_key = source.object_key
    await session.delete(source)
    enqueue_event(
        session,
        tenant_id=principal.tenant_id,
        aggregate_type="knowledge_source",
        aggregate_id=source.id,
        event_type="knowledge.source.deleted.v1",
        payload={
            "sourceId": str(source.id),
            "agentId": str(source.agent_id),
            "objectKey": object_key,
            "extractionKey": source.extraction_key,
        },
    )
    await session.commit()
    return Response(status_code=204)


def _size_label(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"


@router.get("/agents/{agent_id}/facts", response_model=list[FactOut])
async def list_facts(
    agent_id: UUID,
    principal: KnowledgeViewPrincipal,
    session: DB,
    fact_status: FactStatus | None = None,
) -> list[KnowledgeFact]:
    await scoped_agent(
        session, principal.tenant_id, agent_id,
        workspace_id=principal.workspace_id, allowed_agent_ids=principal.agent_ids,
    )
    query = select(KnowledgeFact).where(
        KnowledgeFact.tenant_id == principal.tenant_id,
        KnowledgeFact.workspace_id == principal.workspace_id,
        KnowledgeFact.agent_id == agent_id,
    )
    if fact_status:
        query = query.where(KnowledgeFact.status == fact_status)
    return list((await session.scalars(query.order_by(KnowledgeFact.updated_at.desc()))).all())


@router.post("/agents/{agent_id}/facts", response_model=FactOut, status_code=201)
async def create_fact(
    agent_id: UUID, payload: FactCreate, principal: KnowledgeManagePrincipal, session: DB
) -> KnowledgeFact:
    agent = await scoped_agent(
        session, principal.tenant_id, agent_id,
        workspace_id=principal.workspace_id, allowed_agent_ids=principal.agent_ids,
    )
    vector = await nvidia_adapter.embed_query(f"{payload.question}\n{payload.answer}")
    fact = KnowledgeFact(
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        agent_id=agent_id,
        question=payload.question.strip(),
        answer=payload.answer.strip(),
        status=payload.status,
        priority=payload.priority,
        revision=agent.published_knowledge_revision,
        embedding_model=get_settings().nvidia_embedding_model,
        embedding=vector,
        approved_by=principal.user_id if payload.status == FactStatus.APPROVED else None,
        approved_at=datetime.now(UTC) if payload.status == FactStatus.APPROVED else None,
    )
    session.add(fact)
    enqueue_event(
        session,
        tenant_id=principal.tenant_id,
        aggregate_type="knowledge_fact",
        aggregate_id=fact.id,
        event_type="knowledge.fact.changed.v1",
        payload={"factId": str(fact.id), "agentId": str(agent_id), "status": fact.status.value},
    )
    await session.commit()
    await session.refresh(fact)
    return fact


async def _scoped_fact(
    fact_id: UUID,
    *,
    principal: Principal,
    session: AsyncSession,
) -> KnowledgeFact:
    fact = await session.scalar(
        select(KnowledgeFact).where(
            KnowledgeFact.id == fact_id,
            KnowledgeFact.tenant_id == principal.tenant_id,
            KnowledgeFact.workspace_id == principal.workspace_id,
        )
    )
    if fact is None:
        raise HTTPException(status_code=404, detail="Knowledge fact not found")
    agent = await scoped_agent(
        session,
        principal.tenant_id,
        fact.agent_id,
        workspace_id=principal.workspace_id,
        allowed_agent_ids=principal.agent_ids,
    )
    await require_education_agent(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        agent=agent,
    )
    return fact


@router.get(
    "/facts/{fact_id}/education-scopes",
    response_model=list[EducationKnowledgeScopeOut],
)
async def get_fact_education_scopes(
    fact_id: UUID,
    principal: KnowledgeViewPrincipal,
    session: DB,
) -> list[EducationKnowledgeScopeOut]:
    fact = await _scoped_fact(fact_id, principal=principal, session=session)
    return list(
        await list_fact_scopes(
            session,
            tenant_id=principal.tenant_id,
            workspace_id=principal.workspace_id,
            agent_id=fact.agent_id,
            fact_id=fact.id,
        )
    )


@router.put(
    "/facts/{fact_id}/education-scopes",
    response_model=list[EducationKnowledgeScopeOut],
)
async def set_fact_education_scopes(
    fact_id: UUID,
    payload: EducationKnowledgeScopeReplace,
    principal: KnowledgeManagePrincipal,
    session: DB,
) -> list[EducationKnowledgeScopeOut]:
    fact = await _scoped_fact(fact_id, principal=principal, session=session)
    scopes = await replace_fact_scopes(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        agent_id=fact.agent_id,
        fact_id=fact.id,
        pairs=payload.scopes,
    )
    enqueue_event(
        session,
        tenant_id=principal.tenant_id,
        aggregate_type="knowledge_fact",
        aggregate_id=fact.id,
        event_type="education.knowledge.scope.updated.v1",
        payload={
            "factId": str(fact.id),
            "agentId": str(fact.agent_id),
            "scopes": [{"courseId": str(item.course_id), "batchId": str(item.batch_id)} for item in scopes],
        },
    )
    await session.commit()
    return list(scopes)


@router.patch("/facts/{fact_id}", response_model=FactOut)
async def update_fact(
    fact_id: UUID, payload: FactPatch, principal: KnowledgeManagePrincipal, session: DB
) -> KnowledgeFact:
    fact = await session.scalar(
        select(KnowledgeFact).where(
            KnowledgeFact.id == fact_id,
            KnowledgeFact.tenant_id == principal.tenant_id,
            KnowledgeFact.workspace_id == principal.workspace_id,
        )
    )
    if not fact:
        raise HTTPException(status_code=404, detail="Knowledge fact not found")
    patch = payload.model_dump(exclude_unset=True)
    for name, value in patch.items():
        setattr(fact, name, value)
    if "status" in patch and fact.status == FactStatus.APPROVED:
        fact.approved_by = principal.user_id
        fact.approved_at = datetime.now(UTC)
    if {"question", "answer"} & patch.keys():
        fact.embedding = await nvidia_adapter.embed_query(f"{fact.question}\n{fact.answer}")
        fact.embedding_model = get_settings().nvidia_embedding_model
    enqueue_event(
        session,
        tenant_id=principal.tenant_id,
        aggregate_type="knowledge_fact",
        aggregate_id=fact.id,
        event_type="knowledge.fact.changed.v1",
        payload={"factId": str(fact.id), "agentId": str(fact.agent_id), "status": fact.status.value},
    )
    await session.commit()
    await session.refresh(fact)
    return fact


@router.get("/jobs/{job_id}", response_model=JobOut)
async def get_job(job_id: UUID, principal: KnowledgeViewPrincipal, session: DB) -> JobOut:
    job = await session.scalar(
        select(IngestionJob).where(
            IngestionJob.id == job_id,
            IngestionJob.tenant_id == principal.tenant_id,
            IngestionJob.workspace_id == principal.workspace_id,
        )
    )
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobOut(
        id=job.id,
        source_id=job.source_id,
        status=job.status,
        step=job.step,
        progress=job.progress,
        attempts=job.attempts,
        error=job.error_json,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )
