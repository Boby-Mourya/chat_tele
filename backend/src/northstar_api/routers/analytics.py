from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BeforeValidator
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.agent_purpose import AgentPurpose, AgentPurposeSetting
from northstar_api.analytics_schemas import (
    AgentAnalyticsOut,
    AnalyticsPoint,
    AnalyticsSummaryOut,
    ChannelMetric,
    CRMAnalyticsOut,
    EducationAnalyticsOut,
    LeadAnalyticsOut,
    TopQuestion,
)
from northstar_api.database import get_session
from northstar_api.dependencies import require_permissions
from northstar_api.education_conversation_context import EducationConversationContext
from northstar_api.education_enrollments import EducationEnrollment, EnrollmentStatus
from northstar_api.education_student_activity import EducationStudentActivityEvent
from northstar_api.education_students import EducationStudent, StudentStatus
from northstar_api.lead_crm.domain import (
    CRMDeliveryStatus,
    LeadLifecycleStatus,
    QualificationStatus,
)
from northstar_api.lead_crm.models import CRMDelivery, LeadProfile
from northstar_api.models import (
    Agent,
    AgentStatus,
    Conversation,
    ConversationState,
    Lead,
    Message,
    MessageFeedback,
    MessageRole,
)
from northstar_api.security import Principal

router = APIRouter(prefix="/analytics", tags=["analytics"])
DB = Annotated[AsyncSession, Depends(get_session)]
AnalyticsPrincipal = Annotated[Principal, Depends(require_permissions("analytics.view"))]
AnalyticsDays = Annotated[
    Literal[7, 30, 90],
    BeforeValidator(lambda value: int(value) if isinstance(value, str) and value.isdigit() else value),
]


def _rate(numerator: int, denominator: int) -> float:
    return round(100 * numerator / denominator, 1) if denominator else 0.0


@router.get("/summary", response_model=AnalyticsSummaryOut)
async def analytics_summary(
    principal: AnalyticsPrincipal,
    session: DB,
    days: Annotated[AnalyticsDays, Query()] = 30,
) -> AnalyticsSummaryOut:
    now = datetime.now(UTC)
    current_start = now - timedelta(days=days)
    previous_start = current_start - timedelta(days=days)

    conversation_scope = [
        Conversation.tenant_id == principal.tenant_id,
        Conversation.workspace_id == principal.workspace_id,
    ]
    if principal.agent_ids is not None:
        conversation_scope.append(Conversation.agent_id.in_(principal.agent_ids))

    current_count = int(
        await session.scalar(
            select(func.count())
            .select_from(Conversation)
            .where(*conversation_scope, Conversation.started_at >= current_start)
        )
        or 0
    )
    previous_count = int(
        await session.scalar(
            select(func.count())
            .select_from(Conversation)
            .where(
                *conversation_scope,
                Conversation.started_at >= previous_start,
                Conversation.started_at < current_start,
            )
        )
        or 0
    )
    resolved = int(
        await session.scalar(
            select(func.count())
            .select_from(Conversation)
            .where(
                *conversation_scope,
                Conversation.started_at >= current_start,
                Conversation.state == ConversationState.RESOLVED,
            )
        )
        or 0
    )
    previous_resolved = int(
        await session.scalar(
            select(func.count())
            .select_from(Conversation)
            .where(
                *conversation_scope,
                Conversation.started_at >= previous_start,
                Conversation.started_at < current_start,
                Conversation.state == ConversationState.RESOLVED,
            )
        )
        or 0
    )

    response_conditions = [
        Conversation.tenant_id == principal.tenant_id,
        Conversation.workspace_id == principal.workspace_id,
        Message.role == MessageRole.ASSISTANT,
        Message.created_at >= current_start,
    ]
    if principal.agent_ids is not None:
        response_conditions.append(Conversation.agent_id.in_(principal.agent_ids))
    response_ms = float(
        await session.scalar(
            select(func.avg(Message.latency_ms))
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(*response_conditions)
        )
        or 0
    )

    feedback_conditions = [
        MessageFeedback.tenant_id == principal.tenant_id,
        MessageFeedback.workspace_id == principal.workspace_id,
        MessageFeedback.created_at >= current_start,
        Conversation.tenant_id == principal.tenant_id,
        Conversation.workspace_id == principal.workspace_id,
    ]
    if principal.agent_ids is not None:
        feedback_conditions.append(Conversation.agent_id.in_(principal.agent_ids))
    feedback = (
        await session.execute(
            select(MessageFeedback.value, func.count(MessageFeedback.id).label("count"))
            .join(Message, Message.id == MessageFeedback.message_id)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(*feedback_conditions)
            .group_by(MessageFeedback.value)
        )
    ).all()
    positive_feedback = sum(int(count) for value, count in feedback if int(value) == 1)
    negative_feedback = sum(int(count) for value, count in feedback if int(value) == -1)
    feedback_total = positive_feedback + negative_feedback
    satisfaction = round(5 * positive_feedback / feedback_total, 1) if feedback_total else 0.0

    conversations = (
        await session.scalars(
            select(Conversation)
            .where(*conversation_scope, Conversation.started_at >= current_start)
            .order_by(Conversation.started_at)
        )
    ).all()
    bucket_days = 1 if days == 7 else 4 if days == 30 else 12
    chart: list[AnalyticsPoint] = []
    for offset in range(0, days, bucket_days):
        start = current_start + timedelta(days=offset)
        end = min(start + timedelta(days=bucket_days), now + timedelta(seconds=1))
        bucket = []
        for item in conversations:
            started_at = item.started_at if item.started_at.tzinfo else item.started_at.replace(tzinfo=UTC)
            if start <= started_at < end:
                bucket.append(item)
        chart.append(
            AnalyticsPoint(
                label=start.strftime("%b %d"),
                conversations=len(bucket),
                resolved=sum(item.state == ConversationState.RESOLVED for item in bucket),
            )
        )

    question_conditions = [
        Conversation.tenant_id == principal.tenant_id,
        Conversation.workspace_id == principal.workspace_id,
        Message.role == MessageRole.USER,
        Message.created_at >= current_start,
    ]
    if principal.agent_ids is not None:
        question_conditions.append(Conversation.agent_id.in_(principal.agent_ids))
    top_rows = (
        await session.execute(
            select(
                Message.content,
                func.count(Message.id).label("count"),
                func.sum(case((Conversation.state == ConversationState.RESOLVED, 1), else_=0)).label(
                    "resolved"
                ),
            )
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(*question_conditions)
            .group_by(Message.content)
            .order_by(func.count(Message.id).desc())
            .limit(5)
        )
    ).all()
    top_questions = [
        TopQuestion(
            question=question[:300],
            count=int(count),
            resolution_rate=_rate(int(row_resolved or 0), int(count)),
        )
        for question, count, row_resolved in top_rows
    ]
    channel_counts = Counter(item.channel.value for item in conversations)
    channels = [
        ChannelMetric(channel=channel.replace("_", " ").title(), value=_rate(count, current_count))
        for channel, count in channel_counts.most_common()
    ]

    agent_scope = [
        Agent.tenant_id == principal.tenant_id,
        Agent.workspace_id == principal.workspace_id,
        Agent.deleted_at.is_(None),
    ]
    if principal.agent_ids is not None:
        agent_scope.append(Agent.id.in_(principal.agent_ids))
    total_agents = int(
        await session.scalar(select(func.count()).select_from(Agent).where(*agent_scope)) or 0
    )
    active_agents = int(
        await session.scalar(
            select(func.count()).select_from(Agent).where(
                *agent_scope,
                Agent.status == AgentStatus.ACTIVE,
            )
        )
        or 0
    )

    purpose_scope = [
        Agent.tenant_id == principal.tenant_id,
        Agent.workspace_id == principal.workspace_id,
        Agent.deleted_at.is_(None),
        AgentPurposeSetting.tenant_id == principal.tenant_id,
        AgentPurposeSetting.workspace_id == principal.workspace_id,
    ]
    if principal.agent_ids is not None:
        purpose_scope.append(Agent.id.in_(principal.agent_ids))
    lead_agents = int(
        await session.scalar(
            select(func.count())
            .select_from(AgentPurposeSetting)
            .join(Agent, Agent.id == AgentPurposeSetting.agent_id)
            .where(
                *purpose_scope,
                AgentPurposeSetting.purpose == AgentPurpose.LEAD_GENERATION.value,
            )
        )
        or 0
    )
    education_agents = int(
        await session.scalar(
            select(func.count())
            .select_from(AgentPurposeSetting)
            .join(Agent, Agent.id == AgentPurposeSetting.agent_id)
            .where(
                *purpose_scope,
                AgentPurposeSetting.purpose == AgentPurpose.EDUCATION.value,
            )
        )
        or 0
    )

    lead_scope = [
        Lead.tenant_id == principal.tenant_id,
        Lead.workspace_id == principal.workspace_id,
        Lead.created_at >= current_start,
    ]
    if principal.agent_ids is not None:
        lead_scope.append(Lead.agent_id.in_(principal.agent_ids))
    created_leads = int(
        await session.scalar(select(func.count()).select_from(Lead).where(*lead_scope)) or 0
    )
    qualified_leads = int(
        await session.scalar(
            select(func.count())
            .select_from(Lead)
            .join(LeadProfile, LeadProfile.lead_id == Lead.id)
            .where(
                *lead_scope,
                LeadProfile.tenant_id == principal.tenant_id,
                LeadProfile.qualification_status == QualificationStatus.QUALIFIED.value,
            )
        )
        or 0
    )
    converted_leads = int(
        await session.scalar(
            select(func.count())
            .select_from(Lead)
            .join(LeadProfile, LeadProfile.lead_id == Lead.id)
            .where(
                *lead_scope,
                LeadProfile.tenant_id == principal.tenant_id,
                LeadProfile.lifecycle_status == LeadLifecycleStatus.CONVERTED.value,
            )
        )
        or 0
    )

    crm_scope = [
        CRMDelivery.tenant_id == principal.tenant_id,
        CRMDelivery.created_at >= current_start,
        Lead.tenant_id == principal.tenant_id,
        Lead.workspace_id == principal.workspace_id,
    ]
    if principal.agent_ids is not None:
        crm_scope.append(Lead.agent_id.in_(principal.agent_ids))
    crm_deliveries = int(
        await session.scalar(
            select(func.count())
            .select_from(CRMDelivery)
            .join(Lead, Lead.id == CRMDelivery.lead_id)
            .where(*crm_scope)
        )
        or 0
    )
    crm_verified = int(
        await session.scalar(
            select(func.count())
            .select_from(CRMDelivery)
            .join(Lead, Lead.id == CRMDelivery.lead_id)
            .where(*crm_scope, CRMDelivery.status == CRMDeliveryStatus.VERIFIED.value)
        )
        or 0
    )
    crm_failure_statuses = {
        CRMDeliveryStatus.FAILED.value,
        CRMDeliveryStatus.DEAD_LETTER.value,
        CRMDeliveryStatus.MAPPING_ERROR.value,
        CRMDeliveryStatus.AUTH_REQUIRED.value,
    }
    crm_failed = int(
        await session.scalar(
            select(func.count())
            .select_from(CRMDelivery)
            .join(Lead, Lead.id == CRMDelivery.lead_id)
            .where(*crm_scope, CRMDelivery.status.in_(crm_failure_statuses))
        )
        or 0
    )

    enrollment_scope = [
        EducationEnrollment.tenant_id == principal.tenant_id,
        EducationEnrollment.workspace_id == principal.workspace_id,
    ]
    if principal.agent_ids is not None:
        enrollment_scope.append(EducationEnrollment.agent_id.in_(principal.agent_ids))
    active_enrollments = int(
        await session.scalar(
            select(func.count()).select_from(EducationEnrollment).where(
                *enrollment_scope,
                EducationEnrollment.status == EnrollmentStatus.ACTIVE.value,
            )
        )
        or 0
    )
    if principal.agent_ids is None:
        students = int(
            await session.scalar(
                select(func.count()).select_from(EducationStudent).where(
                    EducationStudent.tenant_id == principal.tenant_id,
                    EducationStudent.workspace_id == principal.workspace_id,
                    EducationStudent.status == StudentStatus.ACTIVE.value,
                )
            )
            or 0
        )
    else:
        students = int(
            await session.scalar(
                select(func.count(func.distinct(EducationEnrollment.student_id)))
                .select_from(EducationEnrollment)
                .join(EducationStudent, EducationStudent.id == EducationEnrollment.student_id)
                .where(
                    *enrollment_scope,
                    EducationStudent.tenant_id == principal.tenant_id,
                    EducationStudent.workspace_id == principal.workspace_id,
                    EducationStudent.status == StudentStatus.ACTIVE.value,
                )
            )
            or 0
        )

    education_conversation_scope = [
        EducationConversationContext.tenant_id == principal.tenant_id,
        EducationConversationContext.workspace_id == principal.workspace_id,
        Conversation.tenant_id == principal.tenant_id,
        Conversation.workspace_id == principal.workspace_id,
        Conversation.started_at >= current_start,
    ]
    if principal.agent_ids is not None:
        education_conversation_scope.append(
            EducationConversationContext.agent_id.in_(principal.agent_ids)
        )
    education_conversations = int(
        await session.scalar(
            select(func.count(func.distinct(Conversation.id)))
            .select_from(EducationConversationContext)
            .join(Conversation, Conversation.id == EducationConversationContext.conversation_id)
            .where(*education_conversation_scope)
        )
        or 0
    )

    activity_scope = [
        EducationStudentActivityEvent.tenant_id == principal.tenant_id,
        EducationStudentActivityEvent.workspace_id == principal.workspace_id,
        EducationStudentActivityEvent.created_at >= current_start,
    ]
    if principal.agent_ids is not None:
        activity_scope.append(EducationStudentActivityEvent.agent_id.in_(principal.agent_ids))
    education_activity = int(
        await session.scalar(
            select(func.count()).select_from(EducationStudentActivityEvent).where(*activity_scope)
        )
        or 0
    )

    current_resolution = _rate(resolved, current_count)
    previous_resolution = _rate(previous_resolved, previous_count)
    conversation_delta = (
        100 * (current_count - previous_count) / previous_count if previous_count else 0
    )
    return AnalyticsSummaryOut(
        period=f"Last {days} days",
        conversations=current_count,
        conversations_delta=round(conversation_delta, 1),
        resolution_rate=current_resolution,
        resolution_delta=round(current_resolution - previous_resolution, 1),
        avg_response_seconds=round(response_ms / 1000, 2),
        satisfaction=satisfaction,
        chart=chart,
        top_questions=top_questions,
        channels=channels,
        agents=AgentAnalyticsOut(
            total=total_agents,
            active=active_agents,
            support=max(0, total_agents - lead_agents - education_agents),
            lead_generation=lead_agents,
            education=education_agents,
        ),
        leads=LeadAnalyticsOut(
            created=created_leads,
            qualified=qualified_leads,
            converted=converted_leads,
            qualification_rate=_rate(qualified_leads, created_leads),
            conversion_rate=_rate(converted_leads, created_leads),
        ),
        crm=CRMAnalyticsOut(
            deliveries=crm_deliveries,
            verified=crm_verified,
            failed=crm_failed,
            success_rate=_rate(crm_verified, crm_deliveries),
        ),
        education=EducationAnalyticsOut(
            students=students,
            active_enrollments=active_enrollments,
            conversations=education_conversations,
            activity_events=education_activity,
        ),
    )
