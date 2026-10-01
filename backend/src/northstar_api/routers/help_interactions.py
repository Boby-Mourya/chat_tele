from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select

from northstar_api.dependencies import CurrentPrincipal, DBSession
from northstar_api.help_config import get_help_settings
from northstar_api.help_models import HelpArticle, HelpArticleFeedback, HelpArticleStatus, HelpSupportRequest
from northstar_api.help_schemas import HelpAiAnswerOut, HelpAskRequest, HelpEventCreate, HelpFeedbackCreate, HelpFeedbackOut, HelpSupportRequestCreate, HelpSupportRequestOut
from northstar_api.models import Role, User
from northstar_api.routers.help_common import _record_event, _role_visible, _sanitize_diagnostics, _summary, _support_destination, _support_out
from northstar_api.services.help_assistant import help_assistant_service
from northstar_api.services.outbox import enqueue_event
from northstar_api.services.rate_limit import redis_services

router = APIRouter()
settings = get_help_settings()

@router.post("/articles/{article_id}/feedback", response_model=HelpFeedbackOut)
async def help_feedback(
    article_id: UUID,
    payload: HelpFeedbackCreate,
    principal: CurrentPrincipal,
    session: DBSession,
) -> HelpFeedbackOut:
    article = await session.scalar(select(HelpArticle).where(HelpArticle.id == article_id, HelpArticle.status == HelpArticleStatus.PUBLISHED))
    if not article:
        raise HTTPException(status_code=404, detail="Help article not found")
    if not _role_visible(article, principal.role):
        raise HTTPException(status_code=403, detail="This guide is not available for your workspace role")
    feedback = await session.scalar(
        select(HelpArticleFeedback).where(
            HelpArticleFeedback.tenant_id == principal.tenant_id,
            HelpArticleFeedback.user_id == principal.user_id,
            HelpArticleFeedback.article_id == article_id,
        )
    )
    if feedback is None:
        feedback = HelpArticleFeedback(
            tenant_id=principal.tenant_id,
            user_id=principal.user_id,
            article_id=article_id,
            helpful=payload.helpful,
        )
        session.add(feedback)
    feedback.helpful = payload.helpful
    feedback.reason = payload.reason
    feedback.comment = payload.comment.strip() if payload.comment else None
    await session.commit()
    await session.refresh(feedback)
    return HelpFeedbackOut(
        article_id=article_id,
        helpful=feedback.helpful,
        reason=feedback.reason,
        comment=feedback.comment,
        updated_at=feedback.updated_at,
    )


@router.post("/ask", response_model=HelpAiAnswerOut)
async def help_ask(
    payload: HelpAskRequest,
    principal: CurrentPrincipal,
    session: DBSession,
) -> HelpAiAnswerOut:
    rate = await redis_services.check_rate_limit(
        f"help-ai:{principal.tenant_id}:{principal.user_id}",
        settings.help_ai_rate_limit_per_minute,
        scope="help_ai",
    )
    if not rate.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many Help AI requests. Try again shortly.",
            headers={"Retry-After": str(rate.retry_after)},
        )
    result = await help_assistant_service.answer(session, role=principal.role, question=payload.question)
    await _record_event(session, principal, "ai_question", query=payload.question, metadata={"available": result.available})
    await session.commit()
    citations = [_summary(item.article, item.category) for item in result.evidence[:5]]
    return HelpAiAnswerOut(
        answer=result.answer,
        citations=citations,
        suggested_articles=citations[:4],
        available=result.available,
    )




@router.post("/events", status_code=204)
async def create_help_event(
    payload: HelpEventCreate,
    principal: CurrentPrincipal,
    session: DBSession,
) -> None:
    article = await session.scalar(
        select(HelpArticle).where(
            HelpArticle.id == payload.article_id,
            HelpArticle.status == HelpArticleStatus.PUBLISHED,
        )
    )
    if not article or not _role_visible(article, principal.role):
        raise HTTPException(status_code=404, detail="Help article not found")
    await _record_event(
        session,
        principal,
        payload.event_type,
        article_id=article.id,
        query=payload.query,
    )
    await session.commit()

@router.post("/support-requests", response_model=HelpSupportRequestOut, status_code=201)
async def create_help_support_request(
    payload: HelpSupportRequestCreate,
    request: Request,
    principal: CurrentPrincipal,
    session: DBSession,
) -> HelpSupportRequestOut:
    user = await session.scalar(select(User).where(User.id == principal.user_id))
    if not user:
        raise HTTPException(status_code=401, detail="Account is unavailable")
    destination = await _support_destination(session, principal.tenant_id)
    diagnostics = _sanitize_diagnostics(payload)
    if payload.include_diagnostics:
        diagnostics.setdefault("userAgent", request.headers.get("user-agent", "")[:500])
    support_request = HelpSupportRequest(
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        requester_role=principal.role.value,
        category=payload.category,
        subject=payload.subject.strip(),
        message=payload.message.strip(),
        context_path=payload.context_path.strip() if payload.context_path else None,
        requester_email=user.email,
        support_destination=str(destination.email),
        diagnostics_json=diagnostics,
    )
    session.add(support_request)
    await session.flush()
    enqueue_event(
        session,
        tenant_id=principal.tenant_id,
        aggregate_type="help_support_request",
        aggregate_id=support_request.id,
        event_type="help.support_request.created.v1",
        payload={
            "requestId": str(support_request.id),
            "userId": str(principal.user_id),
            "category": support_request.category,
            "supportDestination": support_request.support_destination,
            "contextPath": support_request.context_path or "",
        },
    )
    await _record_event(session, principal, "support_request", metadata={"requestId": str(support_request.id), "category": support_request.category})
    await session.commit()
    await session.refresh(support_request)
    return _support_out(support_request)


@router.get("/support-requests", response_model=list[HelpSupportRequestOut])
async def list_help_support_requests(principal: CurrentPrincipal, session: DBSession) -> list[HelpSupportRequestOut]:
    statement = select(HelpSupportRequest).where(HelpSupportRequest.tenant_id == principal.tenant_id)
    if principal.role not in {Role.OWNER, Role.ADMIN}:
        statement = statement.where(HelpSupportRequest.user_id == principal.user_id)
    rows = (await session.scalars(statement.order_by(HelpSupportRequest.created_at.desc()).limit(100))).all()
    return [_support_out(row) for row in rows]


@router.get("/support-requests/{request_id}", response_model=HelpSupportRequestOut)
async def get_help_support_request(request_id: UUID, principal: CurrentPrincipal, session: DBSession) -> HelpSupportRequestOut:
    statement = select(HelpSupportRequest).where(
        HelpSupportRequest.id == request_id,
        HelpSupportRequest.tenant_id == principal.tenant_id,
    )
    if principal.role not in {Role.OWNER, Role.ADMIN}:
        statement = statement.where(HelpSupportRequest.user_id == principal.user_id)
    row = await session.scalar(statement)
    if not row:
        raise HTTPException(status_code=404, detail="Support request not found")
    return _support_out(row)
