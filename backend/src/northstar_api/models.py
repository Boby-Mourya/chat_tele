from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from typing import Any

from pgvector.sqlalchemy import HALFVEC
from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.ext.mutable import MutableDict, MutableList
from sqlalchemy.orm import Mapped, mapped_column, relationship

from northstar_api.config import get_settings
from northstar_api.database import Base

JSONType = JSON().with_variant(JSONB, "postgresql")
MutableJSON = MutableDict.as_mutable(JSONType)
MutableListJSON = MutableList.as_mutable(JSON().with_variant(JSONB, "postgresql"))
EMBEDDING_DIMENSION = get_settings().embedding_dimension


@compiles(HALFVEC, "sqlite")
def compile_halfvec_sqlite(_: HALFVEC, __: Any, **___: Any) -> str:
    return "JSON"


def enum_column(enum_type: type[enum.Enum], name: str) -> SAEnum:
    return SAEnum(
        enum_type,
        name=name,
        native_enum=False,
        values_callable=lambda values: [item.value for item in values],
    )


class Role(str, enum.Enum):
    OWNER = "owner"
    ADMIN = "admin"
    BILLING_ADMIN = "billing_admin"
    SECURITY_ADMIN = "security_admin"
    MEMBER = "member"
    ANALYST = "analyst"


class WorkspaceRole(str, enum.Enum):
    ADMIN = "workspace_admin"
    MANAGER = "manager"
    OPERATOR = "operator"
    ANALYST = "analyst"
    VIEWER = "viewer"


class WorkspaceStatus(str, enum.Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class AgentStatus(str, enum.Enum):
    ACTIVE = "active"
    DRAFT = "draft"
    TRAINING = "training"
    ERROR = "error"


class AgentTone(str, enum.Enum):
    PROFESSIONAL = "professional"
    FRIENDLY = "friendly"
    CONCISE = "concise"
    EMPATHETIC = "empathetic"
    PLAYFUL = "playful"


class KnowledgeKind(str, enum.Enum):
    FILE = "file"
    URL = "url"
    TEXT = "text"
    SITEMAP = "sitemap"


class KnowledgeStatus(str, enum.Enum):
    READY = "ready"
    PROCESSING = "processing"
    NEEDS_REVIEW = "needs_review"
    FAILED = "failed"


class FactStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    ARCHIVED = "archived"


class ConversationState(str, enum.Enum):
    OPEN = "open"
    RESOLVED = "resolved"
    ESCALATED = "escalated"


class Sentiment(str, enum.Enum):
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"


class Channel(str, enum.Enum):
    WIDGET = "widget"
    API = "api"
    SLACK = "slack"
    WHATSAPP = "whatsapp"
    TELEGRAM = "telegram"


class MessageRole(str, enum.Enum):
    USER = "user"
    ASSISTANT = "assistant"
    AGENT = "agent"
    SYSTEM = "system"


class JobStatus(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)


class Tenant(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "tenants"

    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    plan: Mapped[str] = mapped_column(String(40), default="starter")
    settings_json: Mapped[dict[str, Any]] = mapped_column(MutableJSON, default=dict)

    memberships: Mapped[list[TenantMembership]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan"
    )
    workspaces: Mapped[list[Workspace]] = relationship(back_populates="tenant", cascade="all, delete-orphan")
    agents: Mapped[list[Agent]] = relationship(back_populates="tenant", cascade="all, delete-orphan")


class User(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    password_hash: Mapped[str] = mapped_column(String(512))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    memberships: Mapped[list[TenantMembership]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    workspace_memberships: Mapped[list[WorkspaceMembership]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class PlatformAdminAssignment(Base, TimestampMixin):
    """Global platform-control-plane role, deliberately outside tenant roles."""

    __tablename__ = "platform_admin_assignments"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(40), default="support")
    permissions_json: Mapped[dict[str, Any]] = mapped_column(MutableJSON, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TenantMembership(Base, TimestampMixin):
    __tablename__ = "tenant_memberships"
    __table_args__ = (UniqueConstraint("tenant_id", "user_id"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role: Mapped[Role] = mapped_column(enum_column(Role, "membership_role"), default=Role.MEMBER)

    tenant: Mapped[Tenant] = relationship(back_populates="memberships")
    user: Mapped[User] = relationship(back_populates="memberships")


class Workspace(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "workspaces"
    __table_args__ = (
        UniqueConstraint("tenant_id", "slug", name="uq_workspaces_tenant_slug"),
        Index("ix_workspaces_tenant_status", "tenant_id", "status"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    slug: Mapped[str] = mapped_column(String(80))
    status: Mapped[WorkspaceStatus] = mapped_column(
        enum_column(WorkspaceStatus, "workspace_status"), default=WorkspaceStatus.ACTIVE
    )
    timezone: Mapped[str] = mapped_column(String(80), default="Asia/Calcutta")
    default_language: Mapped[str] = mapped_column(String(60), default="English")
    date_format: Mapped[str] = mapped_column(String(24), default="DD/MM/YYYY")
    settings_json: Mapped[dict[str, Any]] = mapped_column(MutableJSON, default=dict)
    branding_json: Mapped[dict[str, Any]] = mapped_column(MutableJSON, default=dict)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    tenant: Mapped[Tenant] = relationship(back_populates="workspaces")
    memberships: Mapped[list[WorkspaceMembership]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )
    agents: Mapped[list[Agent]] = relationship(back_populates="workspace")


class WorkspaceTeamRecord(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Normalized team projection used by routing and operational queries."""

    __tablename__ = "workspace_team_records"
    __table_args__ = (
        UniqueConstraint("workspace_id", "team_id", name="uq_workspace_team_records_id"),
        UniqueConstraint("workspace_id", "name", name="uq_workspace_team_records_name"),
        Index("ix_workspace_team_records_tenant_workspace", "tenant_id", "workspace_id"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    team_id: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(String(500), default="")
    member_ids_json: Mapped[list[str]] = mapped_column(MutableListJSON, default=list)
    manager_ids_json: Mapped[list[str]] = mapped_column(MutableListJSON, default=list)
    role_ids_json: Mapped[list[str]] = mapped_column(MutableListJSON, default=list)
    queue_ids_json: Mapped[list[str]] = mapped_column(MutableListJSON, default=list)
    agent_ids_json: Mapped[list[str]] = mapped_column(MutableListJSON, default=list)
    channel_ids_json: Mapped[list[str]] = mapped_column(MutableListJSON, default=list)
    business_hours_json: Mapped[dict[str, Any]] = mapped_column(MutableJSON, default=dict)
    escalation_rule: Mapped[str] = mapped_column(String(1000), default="")


class WorkspaceSecurityPolicyRecord(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Normalized, tenant-scoped policy used by security enforcement paths."""

    __tablename__ = "workspace_security_policy_records"
    __table_args__ = (
        UniqueConstraint("workspace_id", name="uq_workspace_security_policy_workspace"),
        Index("ix_workspace_security_policy_tenant_workspace", "tenant_id", "workspace_id"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    sensitive_data_masking: Mapped[bool] = mapped_column(Boolean, default=True)
    security_contact: Mapped[str | None] = mapped_column(String(320), nullable=True)
    mfa_enforcement: Mapped[str] = mapped_column(String(16), default="optional")
    session_timeout_minutes: Mapped[int] = mapped_column(Integer, default=480)
    password_min_length: Mapped[int] = mapped_column(Integer, default=12)
    ip_allowlist_json: Mapped[list[str]] = mapped_column(MutableListJSON, default=list)
    ip_denylist_json: Mapped[list[str]] = mapped_column(MutableListJSON, default=list)
    trusted_domains_json: Mapped[list[str]] = mapped_column(MutableListJSON, default=list)
    webhook_signing_required: Mapped[bool] = mapped_column(Boolean, default=True)
    security_notifications: Mapped[bool] = mapped_column(Boolean, default=True)


class WorkspaceDeveloperSettingsRecord(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Normalized developer/webhook policy for workspace API operations."""

    __tablename__ = "workspace_developer_settings_records"
    __table_args__ = (
        UniqueConstraint("workspace_id", name="uq_workspace_developer_settings_workspace"),
        Index("ix_workspace_developer_settings_tenant_workspace", "tenant_id", "workspace_id"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    sandbox_mode: Mapped[bool] = mapped_column(Boolean, default=False)
    webhook_signing_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    webhook_events_json: Mapped[list[str]] = mapped_column(MutableListJSON, default=list)
    rate_limit_per_minute: Mapped[int] = mapped_column(Integer, default=120)
    request_log_retention_days: Mapped[int] = mapped_column(Integer, default=30)
    webhook_retry_limit: Mapped[int] = mapped_column(Integer, default=5)


class WorkspaceNotificationSettingsRecord(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Normalized notification preferences for workspace operations."""

    __tablename__ = "workspace_notification_settings_records"
    __table_args__ = (
        UniqueConstraint("workspace_id", name="uq_workspace_notification_settings_workspace"),
        Index("ix_workspace_notification_settings_tenant_workspace", "tenant_id", "workspace_id"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    member_changes: Mapped[bool] = mapped_column(Boolean, default=True)
    security_alerts: Mapped[bool] = mapped_column(Boolean, default=True)
    billing_alerts: Mapped[bool] = mapped_column(Boolean, default=True)
    channel_failures: Mapped[bool] = mapped_column(Boolean, default=True)
    integration_failures: Mapped[bool] = mapped_column(Boolean, default=True)
    weekly_digest: Mapped[bool] = mapped_column(Boolean, default=False)
    recipients_json: Mapped[list[str]] = mapped_column(MutableListJSON, default=list)


class WorkspaceMembership(Base, TimestampMixin):
    __tablename__ = "workspace_memberships"
    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id", name="uq_workspace_memberships_workspace_user"),
        Index("ix_workspace_memberships_tenant_user", "tenant_id", "user_id"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    role: Mapped[WorkspaceRole] = mapped_column(
        enum_column(WorkspaceRole, "workspace_membership_role"), default=WorkspaceRole.VIEWER
    )
    all_agents_access: Mapped[bool] = mapped_column(Boolean, default=True)

    workspace: Mapped[Workspace] = relationship(back_populates="memberships")
    user: Mapped[User] = relationship(back_populates="workspace_memberships")


class WorkspaceMemberAgentAccess(Base, TimestampMixin):
    __tablename__ = "workspace_member_agent_access"
    __table_args__ = (Index("ix_workspace_agent_access_user", "workspace_id", "user_id"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True)


def default_appearance() -> dict[str, Any]:
    return {
        "primaryColor": "#146cf6",
        "surfaceColor": "#f6f8fb",
        "position": "bottom-right",
        "launcherStyle": "spark",
        "welcomeTitle": "How can I help you?",
        "welcomeMessage": "Ask a question and I'll find the most useful answer.",
        "placeholder": "Ask me anything...",
        "suggestedQuestions": [
            "What services do you offer?",
            "How can I contact support?",
            "Tell me about your plans.",
        ],
        "showBranding": True,
        "widgetWidth": 380,
        "widgetHeight": 680,
        "pageMargin": 24,
        "textDirection": "ltr",
        "elevatedShadow": True,
        "openOnPageLoad": False,
        "fontFamily": "Inter",
        "cornerRadius": 24,
        "greetingMode": "once",
        "interfaceLanguage": "English",
        "detectBrowserLanguage": True,
        "translations": {
            "newConversation": "New conversation",
            "sendButton": "Send",
            "closeChat": "Close chat",
            "offlineMessage": "We'll be back soon",
        },
        "requireConsent": False,
        "consentMessage": "I agree that my messages may be processed to answer my request.",
        "privacyPolicyUrl": "",
        "widgetName": "",
        "zIndex": 99999,
        "customDomain": "",
        "deploymentChannel": "website",
    }


def default_model_profile() -> dict[str, Any]:
    settings = get_settings()
    return {
        "provider": "nvidia",
        "model": settings.nvidia_model,
        "internetAccess": "none",
        "temperature": settings.nvidia_temperature,
        "topP": settings.nvidia_top_p,
        "maxTokens": settings.nvidia_max_tokens,
        "enableThinking": settings.nvidia_enable_thinking,
        "citationMode": "when-available",
        "rerankCandidates": 60,
        "finalContextChunks": 8,
    }


def default_security() -> dict[str, Any]:
    return {
        "allowedDomains": ["localhost"],
        "rateLimitPerMinute": get_settings().default_rate_limit_per_minute,
        "collectEmail": False,
        "maskSensitiveData": True,
        "retentionDays": 90,
        "webFallback": "off",
        "webAllowedDomains": [],
        "blockedTopics": [],
    }


class Agent(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "agents"
    __table_args__ = (
        UniqueConstraint("workspace_id", "name", name="uq_agents_workspace_name"),
        Index("ix_agents_workspace_status", "workspace_id", "status"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    # Nullable for legacy tenant-scoped agents created before workspace
    # isolation was introduced; all new API-created agents always set it.
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=True
    )
    public_id: Mapped[str] = mapped_column(String(48), unique=True, default=lambda: f"agt_{uuid.uuid4().hex}")
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(String(500), default="")
    instructions: Mapped[str] = mapped_column(
        Text, default="Answer accurately using only approved knowledge."
    )
    status: Mapped[AgentStatus] = mapped_column(
        enum_column(AgentStatus, "agent_status"), default=AgentStatus.DRAFT
    )
    tone: Mapped[AgentTone] = mapped_column(enum_column(AgentTone, "agent_tone"), default=AgentTone.FRIENDLY)
    language: Mapped[str] = mapped_column(String(60), default="English")
    avatar: Mapped[str] = mapped_column(String(500), default="N")
    appearance: Mapped[dict[str, Any]] = mapped_column(MutableJSON, default=default_appearance)
    model_profile: Mapped[dict[str, Any]] = mapped_column(MutableJSON, default=default_model_profile)
    security: Mapped[dict[str, Any]] = mapped_column(MutableJSON, default=default_security)
    published_knowledge_revision: Mapped[int] = mapped_column(Integer, default=1)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    tenant: Mapped[Tenant] = relationship(back_populates="agents")
    workspace: Mapped[Workspace] = relationship(back_populates="agents")
    knowledge_sources: Mapped[list[KnowledgeSource]] = relationship(
        back_populates="agent", cascade="all, delete-orphan"
    )
    conversations: Mapped[list[Conversation]] = relationship(back_populates="agent")


class LLMConnection(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Workspace-scoped model provider credentials.

    ``credentials_encrypted`` contains an authenticated ciphertext payload such
    as ``{"apiKey": "…"}``; it is never serialized to the browser. Agents keep
    only the connection id in their model profile.
    """

    __tablename__ = "llm_connections"
    __table_args__ = (
        UniqueConstraint("workspace_id", "name", name="uq_llm_connections_workspace_name"),
        Index("ix_llm_connections_scope", "tenant_id", "workspace_id", "provider"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    provider: Mapped[str] = mapped_column(String(40))
    endpoint_url: Mapped[str] = mapped_column(String(500))
    credentials_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="configured")
    metadata_json: Mapped[dict[str, Any]] = mapped_column(MutableJSON, default=dict)


class KnowledgeSource(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "knowledge_sources"
    __table_args__ = (
        UniqueConstraint("tenant_id", "agent_id", "name"),
        Index("ix_knowledge_sources_agent_status", "tenant_id", "agent_id", "status"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(240))
    kind: Mapped[KnowledgeKind] = mapped_column(enum_column(KnowledgeKind, "knowledge_kind"))
    status: Mapped[KnowledgeStatus] = mapped_column(
        enum_column(KnowledgeStatus, "knowledge_status"), default=KnowledgeStatus.PROCESSING
    )
    size_label: Mapped[str] = mapped_column(String(80), default="Queued")
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    url: Mapped[str | None] = mapped_column(String(2048))
    content: Mapped[str | None] = mapped_column(Text)
    object_key: Mapped[str | None] = mapped_column(String(1000))
    checksum: Mapped[str | None] = mapped_column(String(64), index=True)
    extraction_key: Mapped[str | None] = mapped_column(String(1000))
    extraction_issue_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(String(1000))
    revision: Mapped[int] = mapped_column(Integer, default=1)

    agent: Mapped[Agent] = relationship(back_populates="knowledge_sources")
    chunks: Mapped[list[DocumentChunk]] = relationship(back_populates="source", cascade="all, delete-orphan")
    facts: Mapped[list[KnowledgeFact]] = relationship(back_populates="source", cascade="all, delete-orphan")


class DocumentChunk(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint("source_id", "ordinal", "revision"),
        Index("ix_document_chunks_scope", "tenant_id", "agent_id", "approved", "revision"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge_sources.id", ondelete="CASCADE"), index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int] = mapped_column(Integer)
    approved: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    embedding_model: Mapped[str | None] = mapped_column(String(200))
    embedding: Mapped[list[float] | None] = mapped_column(HALFVEC(EMBEDDING_DIMENSION))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(MutableJSON, default=dict)

    source: Mapped[KnowledgeSource] = relationship(back_populates="chunks")


class KnowledgeFact(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "knowledge_facts"
    __table_args__ = (Index("ix_knowledge_facts_scope", "tenant_id", "agent_id", "status", "revision"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("knowledge_sources.id", ondelete="SET NULL"), index=True
    )
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    status: Mapped[FactStatus] = mapped_column(
        enum_column(FactStatus, "fact_status"), default=FactStatus.PENDING
    )
    priority: Mapped[int] = mapped_column(Integer, default=0)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    embedding_model: Mapped[str | None] = mapped_column(String(200))
    embedding: Mapped[list[float] | None] = mapped_column(HALFVEC(EMBEDDING_DIMENSION))
    source_span: Mapped[dict[str, Any]] = mapped_column(MutableJSON, default=dict)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    source: Mapped[KnowledgeSource | None] = relationship(back_populates="facts")


class IngestionJob(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "ingestion_jobs"

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge_sources.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[JobStatus] = mapped_column(enum_column(JobStatus, "job_status"), default=JobStatus.QUEUED)
    step: Mapped[str] = mapped_column(String(80), default="queued")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True)
    error_json: Mapped[dict[str, Any]] = mapped_column(MutableJSON, default=dict)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    dispatch_attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_dispatch_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class KnowledgeSnapshot(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Immutable identity for the knowledge revision used by a conversation."""

    __tablename__ = "knowledge_snapshots"
    __table_args__ = (UniqueConstraint("agent_id", "revision"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), index=True
    )
    revision: Mapped[int] = mapped_column(Integer)
    manifest: Mapped[dict[str, Any]] = mapped_column(MutableJSON, default=dict)


class KnowledgeAnswerAudit(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Persist the policy and evidence decision behind each completed answer."""

    __tablename__ = "knowledge_answer_audits"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), index=True
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL")
    )
    snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("knowledge_snapshots.id", ondelete="SET NULL")
    )
    details: Mapped[dict[str, Any]] = mapped_column(MutableJSON, default=dict)


class Conversation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "conversations"
    __table_args__ = (
        Index("ix_conversations_scope_updated", "tenant_id", "workspace_id", "agent_id", "updated_at"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id", ondelete="RESTRICT"), index=True)
    public_id: Mapped[str] = mapped_column(String(48), unique=True, default=lambda: f"cnv_{uuid.uuid4().hex}")
    visitor_id: Mapped[str | None] = mapped_column(String(128), index=True)
    visitor_name: Mapped[str] = mapped_column(String(160), default="Anonymous visitor")
    visitor_email: Mapped[str | None] = mapped_column(String(320))
    channel: Mapped[Channel] = mapped_column(
        enum_column(Channel, "conversation_channel"), default=Channel.WIDGET
    )
    state: Mapped[ConversationState] = mapped_column(
        enum_column(ConversationState, "conversation_state"), default=ConversationState.OPEN
    )
    sentiment: Mapped[Sentiment] = mapped_column(
        enum_column(Sentiment, "sentiment"), default=Sentiment.NEUTRAL
    )
    unread_count: Mapped[int] = mapped_column(Integer, default=0)
    knowledge_revision: Mapped[int] = mapped_column(Integer, default=1)
    page_url: Mapped[str | None] = mapped_column(String(2048))
    visitor_details: Mapped[dict[str, Any]] = mapped_column(MutableJSON, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution: Mapped[str | None] = mapped_column(String(120))

    agent: Mapped[Agent] = relationship(back_populates="conversations")
    messages: Mapped[list[Message]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", order_by="Message.sequence"
    )


class BotWorkflow(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "bot_workflows"
    __table_args__ = (
        UniqueConstraint("agent_id", name="uq_bot_workflows_agent"),
        Index("ix_bot_workflows_scope", "tenant_id", "workspace_id", "purpose", "status"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    purpose: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default="draft")
    steps_json: Mapped[list[dict[str, Any]]] = mapped_column(MutableListJSON, default=list)


class Message(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint(
            "conversation_id",
            "sequence",
            name="uq_messages_conversation_sequence",
        ),
        UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_messages_tenant_idempotency",
        ),
        Index("ix_messages_tenant_created", "tenant_id", "created_at"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    sequence: Mapped[int] = mapped_column(Integer)
    role: Mapped[MessageRole] = mapped_column(enum_column(MessageRole, "message_role"))
    content: Mapped[str] = mapped_column(Text)
    content_json: Mapped[dict[str, Any]] = mapped_column(MutableJSON, default=dict)
    content_fingerprint: Mapped[str | None] = mapped_column(String(64))
    idempotency_key: Mapped[str | None] = mapped_column(String(128))
    model_request_id: Mapped[str | None] = mapped_column(String(200))
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    confidence: Mapped[float | None] = mapped_column(Float)
    finish_reason: Mapped[str | None] = mapped_column(String(80))
    processing_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    conversation: Mapped[Conversation] = relationship(back_populates="messages")
    citations: Mapped[list[MessageCitation]] = relationship(
        back_populates="message", cascade="all, delete-orphan"
    )


class MessageCitation(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "message_citations"

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    message_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), index=True)
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("knowledge_sources.id", ondelete="SET NULL")
    )
    fact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("knowledge_facts.id", ondelete="SET NULL"))
    chunk_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("document_chunks.id", ondelete="SET NULL"))
    rank: Mapped[int] = mapped_column(Integer)
    retrieval_score: Mapped[float] = mapped_column(Float)
    title: Mapped[str] = mapped_column(String(240))
    url: Mapped[str | None] = mapped_column(String(2048))

    message: Mapped[Message] = relationship(back_populates="citations")


class MessageFeedback(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "message_feedback"
    __table_args__ = (UniqueConstraint("tenant_id", "message_id"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    message_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), index=True)
    value: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str | None] = mapped_column(String(500))


class Lead(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "leads"
    __table_args__ = (Index("ix_leads_scope_created", "tenant_id", "workspace_id", "agent_id", "created_at"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), index=True
    )
    name: Mapped[str | None] = mapped_column(String(160))
    email: Mapped[str | None] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(40), default="new")
    consent: Mapped[bool] = mapped_column(Boolean, default=False)
    fields_json: Mapped[dict[str, Any]] = mapped_column(MutableJSON, default=dict)


class IntegrationConnection(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "integration_connections"
    __table_args__ = (UniqueConstraint("workspace_id", "integration_id"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    integration_id: Mapped[str] = mapped_column(String(80))
    connected: Mapped[bool] = mapped_column(Boolean, default=False)
    config_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)


class WhatsAppBusinessAccount(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "whatsapp_business_accounts"
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(160))
    waba_id: Mapped[str] = mapped_column(String(80), unique=True)
    app_id: Mapped[str] = mapped_column(String(80))
    credentials_encrypted: Mapped[bytes] = mapped_column(LargeBinary)
    status: Mapped[str] = mapped_column(String(32), default="needs_webhook")


class WhatsAppConnection(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One active WhatsApp Cloud API number linked to a workspace agent."""

    __tablename__ = "whatsapp_connections"
    __table_args__ = (
        UniqueConstraint("workspace_id", "agent_id", name="uq_whatsapp_connections_workspace_agent"),
        UniqueConstraint("phone_number_id", name="uq_whatsapp_connections_phone_number_id"),
        Index("ix_whatsapp_connections_scope", "tenant_id", "agent_id"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agents.id", ondelete="RESTRICT"), index=True, nullable=True
    )
    business_account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("whatsapp_business_accounts.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    waba_id: Mapped[str] = mapped_column(String(80))
    phone_number_id: Mapped[str] = mapped_column(String(80))
    display_phone_number: Mapped[str] = mapped_column(String(80), default="")
    verified_name: Mapped[str] = mapped_column(String(240), default="")
    access_token_encrypted: Mapped[bytes] = mapped_column(LargeBinary)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), default="connected")
    last_error: Mapped[str | None] = mapped_column(String(500))
    connected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class WhatsAppInboundMessage(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Durable webhook receipt and processing state for an inbound Meta message."""

    __tablename__ = "whatsapp_inbound_messages"
    __table_args__ = (
        UniqueConstraint("provider_message_id", name="uq_whatsapp_inbound_provider_message_id"),
        Index("ix_whatsapp_inbound_dispatch", "status", "next_dispatch_at"),
        Index("ix_whatsapp_inbound_scope", "tenant_id", "connection_id", "created_at"),
        Index("ix_whatsapp_inbound_phone_scope", "tenant_id", "phone_number_id", "created_at"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    connection_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("whatsapp_connections.id", ondelete="SET NULL"), index=True, nullable=True
    )
    phone_number_id: Mapped[str] = mapped_column(String(80))
    provider_message_id: Mapped[str] = mapped_column(String(160))
    sender_wa_id: Mapped[str] = mapped_column(String(80))
    sender_name: Mapped[str | None] = mapped_column(String(160))
    message_type: Mapped[str] = mapped_column(String(40))
    message_text: Mapped[str] = mapped_column(Text)
    provider_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), default="queued")
    dispatch_attempts: Mapped[int] = mapped_column(Integer, default=0)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_dispatch_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outbound_message_id: Mapped[str | None] = mapped_column(String(160))
    outbound_message_ids: Mapped[list[str]] = mapped_column(MutableListJSON, default=list)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), index=True
    )
    last_error: Mapped[str | None] = mapped_column(String(500))


class WhatsAppDeliveryReceipt(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Signed provider delivery evidence, independent of queue processing state."""

    __tablename__ = "whatsapp_delivery_receipts"
    __table_args__ = (
        UniqueConstraint("connection_id", "provider_message_id", "status", name="uq_wa_delivery_receipt"),
        Index("ix_wa_delivery_receipt_scope", "tenant_id", "workspace_id", "connection_id", "created_at"),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("whatsapp_connections.id", ondelete="CASCADE")
    )
    provider_message_id: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(20))
    provider_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(40))


class WhatsAppOutboundDelivery(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Durable queued delivery for a human reply to a WhatsApp conversation."""

    __tablename__ = "whatsapp_outbound_deliveries"
    __table_args__ = (
        UniqueConstraint("message_id", name="uq_whatsapp_outbound_message_id"),
        Index("ix_whatsapp_outbound_dispatch", "status", "next_dispatch_at"),
        Index("ix_whatsapp_outbound_scope", "tenant_id", "connection_id", "created_at"),
        Index("ix_whatsapp_outbound_phone_scope", "tenant_id", "phone_number_id", "created_at"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    connection_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("whatsapp_connections.id", ondelete="SET NULL"), index=True, nullable=True
    )
    phone_number_id: Mapped[str] = mapped_column(String(80))
    message_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), index=True)
    recipient_wa_id: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(32), default="queued")
    dispatch_attempts: Mapped[int] = mapped_column(Integer, default=0)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_dispatch_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider_message_ids: Mapped[list[str]] = mapped_column(MutableListJSON, default=list)
    template_payload: Mapped[dict[str, Any] | None] = mapped_column(MutableJSON, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(500))


class AgentHealthDaily(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "agent_health_daily"
    __table_args__ = (UniqueConstraint("workspace_id", "agent_id", "day"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    day: Mapped[date] = mapped_column(Date)
    conversations: Mapped[int] = mapped_column(Integer, default=0)
    responses: Mapped[int] = mapped_column(Integer, default=0)
    resolved: Mapped[int] = mapped_column(Integer, default=0)
    escalated: Mapped[int] = mapped_column(Integer, default=0)
    response_ms_total: Mapped[int] = mapped_column(Integer, default=0)
    positive_feedback: Mapped[int] = mapped_column(Integer, default=0)
    negative_feedback: Mapped[int] = mapped_column(Integer, default=0)


class OutboxEvent(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "outbox_events"
    __table_args__ = (Index("ix_outbox_unpublished", "published_at", "occurred_at"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    aggregate_type: Mapped[str] = mapped_column(String(80))
    aggregate_id: Mapped[str] = mapped_column(String(80))
    event_type: Mapped[str] = mapped_column(String(160))
    payload: Mapped[dict[str, Any]] = mapped_column(MutableJSON)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(String(500))


class ProcessedEvent(Base):
    __tablename__ = "processed_events"

    event_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    consumer: Mapped[str] = mapped_column(String(120), primary_key=True)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EventQuarantine(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "event_quarantine"
    __table_args__ = (UniqueConstraint("consumer", "topic", "partition", "offset"),)

    consumer: Mapped[str] = mapped_column(String(120))
    topic: Mapped[str] = mapped_column(String(200))
    partition: Mapped[int] = mapped_column(Integer)
    offset: Mapped[int] = mapped_column(Integer)
    payload_sha256: Mapped[str] = mapped_column(String(64))
    payload_excerpt: Mapped[str] = mapped_column(Text)
    error: Mapped[str] = mapped_column(String(500))
    quarantined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
