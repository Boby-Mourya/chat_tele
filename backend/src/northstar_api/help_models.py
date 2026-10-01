from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import HALFVEC
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from northstar_api.database import Base
from northstar_api.models import (
    EMBEDDING_DIMENSION,
    MutableJSON,
    MutableListJSON,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    enum_column,
)


class HelpArticleStatus(str, enum.Enum):
    DRAFT = 'draft'
    PUBLISHED = 'published'
    ARCHIVED = 'archived'


class HelpSupportStatus(str, enum.Enum):
    SUBMITTED = 'submitted'
    ACKNOWLEDGED = 'acknowledged'
    CLOSED = 'closed'


class HelpFeedbackReason(str, enum.Enum):
    INCORRECT = 'incorrect'
    OUTDATED = 'outdated'
    MISSING_STEPS = 'missing_steps'
    HARD_TO_UNDERSTAND = 'hard_to_understand'
    DID_NOT_SOLVE_PROBLEM = 'did_not_solve_problem'
    OTHER = 'other'


class HelpCategory(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = 'help_categories'

    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(String(500), default='')
    icon: Mapped[str] = mapped_column(String(80), default='CircleHelp')
    sort_order: Mapped[int] = mapped_column(Integer, default=0, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    articles: Mapped[list[HelpArticle]] = relationship(back_populates='category', cascade='all, delete-orphan')


class HelpArticle(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = 'help_articles'
    __table_args__ = (Index('ix_help_articles_category_status', 'category_id', 'status', 'sort_order'),)

    category_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('help_categories.id', ondelete='CASCADE'), index=True)
    slug: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(240))
    summary: Mapped[str] = mapped_column(String(1000), default='')
    body_markdown: Mapped[str] = mapped_column(Text)
    keywords_json: Mapped[list[str]] = mapped_column(MutableListJSON, default=list)
    audience_roles_json: Mapped[list[str]] = mapped_column(MutableListJSON, default=list)
    featured: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    status: Mapped[HelpArticleStatus] = mapped_column(
        enum_column(HelpArticleStatus, 'help_article_status'), default=HelpArticleStatus.PUBLISHED, index=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    reading_minutes: Mapped[int] = mapped_column(Integer, default=1)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    category: Mapped[HelpCategory] = relationship(back_populates='articles')
    chunks: Mapped[list[HelpArticleChunk]] = relationship(
        back_populates='article', cascade='all, delete-orphan', order_by='HelpArticleChunk.chunk_index'
    )


class HelpArticleChunk(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = 'help_article_chunks'
    __table_args__ = (
        UniqueConstraint('article_id', 'chunk_index', name='uq_help_article_chunks_article_chunk'),
        Index('ix_help_article_chunks_article', 'article_id', 'chunk_index'),
    )

    article_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('help_articles.id', ondelete='CASCADE'), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    heading_path: Mapped[str] = mapped_column(String(500), default='')
    content: Mapped[str] = mapped_column(Text)
    embedding_model: Mapped[str | None] = mapped_column(String(200))
    embedding: Mapped[list[float] | None] = mapped_column(HALFVEC(EMBEDDING_DIMENSION))

    article: Mapped[HelpArticle] = relationship(back_populates='chunks')


class HelpArticleFeedback(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = 'help_article_feedback'
    __table_args__ = (
        UniqueConstraint('tenant_id', 'user_id', 'article_id', name='uq_help_feedback_tenant_user_article'),
        Index('ix_help_feedback_tenant_article', 'tenant_id', 'article_id', 'created_at'),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('tenants.id', ondelete='CASCADE'), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    article_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('help_articles.id', ondelete='CASCADE'), index=True)
    helpful: Mapped[bool] = mapped_column(Boolean)
    reason: Mapped[HelpFeedbackReason | None] = mapped_column(
        enum_column(HelpFeedbackReason, 'help_feedback_reason'), nullable=True
    )
    comment: Mapped[str | None] = mapped_column(Text)


class HelpEvent(Base, UUIDPrimaryKeyMixin):
    __tablename__ = 'help_events'
    __table_args__ = (
        Index('ix_help_events_tenant_created', 'tenant_id', 'created_at'),
        Index('ix_help_events_article_type', 'article_id', 'event_type'),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('tenants.id', ondelete='CASCADE'), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    article_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('help_articles.id', ondelete='SET NULL'), index=True)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    query: Mapped[str | None] = mapped_column(String(300))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(MutableJSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class HelpSupportRequest(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = 'help_support_requests'
    __table_args__ = (
        Index('ix_help_support_tenant_created', 'tenant_id', 'created_at'),
        Index('ix_help_support_tenant_user', 'tenant_id', 'user_id', 'created_at'),
        Index('ix_help_support_tenant_status', 'tenant_id', 'status', 'created_at'),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('tenants.id', ondelete='CASCADE'), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    requester_role: Mapped[str] = mapped_column(String(32))
    category: Mapped[str] = mapped_column(String(40), index=True)
    subject: Mapped[str] = mapped_column(String(200))
    message: Mapped[str] = mapped_column(Text)
    status: Mapped[HelpSupportStatus] = mapped_column(
        enum_column(HelpSupportStatus, 'help_support_status'), default=HelpSupportStatus.SUBMITTED, index=True
    )
    context_path: Mapped[str | None] = mapped_column(String(500))
    requester_email: Mapped[str] = mapped_column(String(320))
    support_destination: Mapped[str] = mapped_column(String(320))
    diagnostics_json: Mapped[dict[str, Any]] = mapped_column(MutableJSON, default=dict)
