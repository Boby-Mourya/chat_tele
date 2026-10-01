from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import EmailStr, Field, field_validator, model_validator

from northstar_api.help_models import HelpFeedbackReason, HelpSupportStatus
from northstar_api.models import Role
from northstar_api.schemas import APIModel


class HelpCategoryOut(APIModel):
    id: UUID
    slug: str
    title: str
    description: str
    icon: str
    article_count: int
    sort_order: int


class HelpArticleSummaryOut(APIModel):
    id: UUID
    slug: str
    category_slug: str
    category_title: str
    title: str
    summary: str
    keywords: list[str]
    reading_minutes: int
    updated_at: datetime
    featured: bool
    audience_roles: list[Role]


class HelpArticleOut(HelpArticleSummaryOut):
    body_markdown: str
    related: list[HelpArticleSummaryOut] = Field(default_factory=list)
    previous: HelpArticleSummaryOut | None = None
    next: HelpArticleSummaryOut | None = None


class HelpSearchResultOut(HelpArticleSummaryOut):
    score: float
    snippet: str


class HelpSearchPageOut(APIModel):
    items: list[HelpSearchResultOut]
    total: int
    page: int
    page_size: int
    query: str
    suggested_category: str | None = None


class HelpSupportDestinationOut(APIModel):
    email: EmailStr
    external_url: str = ''


class HelpHomeOut(APIModel):
    categories: list[HelpCategoryOut]
    popular: list[HelpArticleSummaryOut]
    recommended: list[HelpArticleSummaryOut]
    support: HelpSupportDestinationOut


class HelpCategoryDetailOut(APIModel):
    category: HelpCategoryOut
    articles: list[HelpArticleSummaryOut]


class HelpFeedbackCreate(APIModel):
    helpful: bool
    reason: HelpFeedbackReason | None = None
    comment: str | None = Field(default=None, max_length=1000)

    @model_validator(mode='after')
    def validate_reason(self) -> 'HelpFeedbackCreate':
        if self.helpful and self.reason is not None:
            raise ValueError('positive feedback must not include a negative reason')
        if not self.helpful and self.reason is None:
            raise ValueError('negative feedback requires a reason')
        return self


class HelpFeedbackOut(APIModel):
    article_id: UUID
    helpful: bool
    reason: HelpFeedbackReason | None = None
    comment: str | None = None
    updated_at: datetime


class HelpAskRequest(APIModel):
    question: str = Field(min_length=2, max_length=2000)

    @field_validator('question')
    @classmethod
    def normalize_help_question(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 2:
            raise ValueError('question is too short')
        return normalized


class HelpAiAnswerOut(APIModel):
    answer: str
    citations: list[HelpArticleSummaryOut]
    suggested_articles: list[HelpArticleSummaryOut]
    available: bool = True


HelpSupportCategory = Literal[
    'account', 'agents', 'knowledge', 'conversations', 'integrations',
    'deploy', 'workspace', 'billing', 'security', 'other'
]


class HelpSupportRequestCreate(APIModel):
    category: HelpSupportCategory
    subject: str = Field(min_length=3, max_length=200)
    message: str = Field(min_length=10, max_length=8000)
    context_path: str | None = Field(default=None, max_length=500)
    include_diagnostics: bool = True
    diagnostics: dict[str, str] = Field(default_factory=dict)

    @field_validator('subject', 'message')
    @classmethod
    def strip_support_text(cls, value: str) -> str:
        return value.strip()


HelpEventType = Literal['search_click', 'ai_citation_click']


class HelpEventCreate(APIModel):
    event_type: HelpEventType
    article_id: UUID
    query: str | None = Field(default=None, max_length=300)

    @field_validator('query')
    @classmethod
    def normalize_help_event_query(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class HelpSupportRequestOut(APIModel):
    id: UUID
    category: str
    subject: str
    message: str
    status: HelpSupportStatus
    context_path: str | None = None
    requester_email: EmailStr
    support_destination: EmailStr
    diagnostics: dict[str, Any]
    created_at: datetime
    updated_at: datetime
