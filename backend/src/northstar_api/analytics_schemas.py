from __future__ import annotations

from northstar_api.schemas import APIModel


class AnalyticsPoint(APIModel):
    label: str
    conversations: int
    resolved: int


class TopQuestion(APIModel):
    question: str
    count: int
    resolution_rate: float


class ChannelMetric(APIModel):
    channel: str
    value: float


class AgentAnalyticsOut(APIModel):
    total: int
    active: int
    support: int
    lead_generation: int
    education: int


class LeadAnalyticsOut(APIModel):
    created: int
    qualified: int
    converted: int
    qualification_rate: float
    conversion_rate: float


class CRMAnalyticsOut(APIModel):
    deliveries: int
    verified: int
    failed: int
    success_rate: float


class EducationAnalyticsOut(APIModel):
    students: int
    active_enrollments: int
    conversations: int
    activity_events: int


class AnalyticsSummaryOut(APIModel):
    period: str
    conversations: int
    conversations_delta: float
    resolution_rate: float
    resolution_delta: float
    avg_response_seconds: float
    satisfaction: float
    chart: list[AnalyticsPoint]
    top_questions: list[TopQuestion]
    channels: list[ChannelMetric]
    agents: AgentAnalyticsOut
    leads: LeadAnalyticsOut
    crm: CRMAnalyticsOut
    education: EducationAnalyticsOut
