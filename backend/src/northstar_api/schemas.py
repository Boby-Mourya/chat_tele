from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, HttpUrl, field_validator, model_validator

from northstar_api.agent_purpose import AgentPurpose
from northstar_api.lead_crm.domain import LeadLifecycleStatus
from northstar_api.models import (
    AgentStatus,
    AgentTone,
    Channel,
    ConversationState,
    FactStatus,
    JobStatus,
    KnowledgeKind,
    KnowledgeStatus,
    MessageRole,
    Role,
    Sentiment,
)


def to_camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(item.capitalize() for item in rest)


class APIModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, from_attributes=True, extra="forbid"
    )


class ErrorDetail(APIModel):
    code: str
    message: str
    request_id: str | None = None


class ErrorResponse(APIModel):
    error: ErrorDetail


class LoginRequest(APIModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=256)
    workspace: str | None = Field(default=None, min_length=1, max_length=80, pattern=r"^[a-z0-9-]+$")


class RefreshRequest(APIModel):
    refresh_token: str | None = None


class LogoutRequest(APIModel):
    refresh_token: str | None = None


class UserOut(APIModel):
    id: UUID
    name: str
    email: EmailStr
    role: Role


class SessionOut(APIModel):
    access_token: str
    expires_at: datetime
    user: UserOut
    refresh_token: str | None = None


class WhatsAppMessageSettings(APIModel):
    welcome_enabled: bool = True
    welcome_message: str | None = Field(default=None, max_length=4096)
    reply_template: str = Field(default="{message}", min_length=1, max_length=1500)

    @model_validator(mode="after")
    def nonempty_welcome(self) -> WhatsAppMessageSettings:
        if self.welcome_enabled and self.welcome_message is not None and not self.welcome_message.strip():
            raise ValueError("Enter a welcome message or turn it off")
        return self

    @field_validator("reply_template")
    @classmethod
    def valid_reply_template(cls, value: str) -> str:
        if value.count("{message}") != 1:
            raise ValueError("Include {message} exactly once in the reply structure")
        remainder = value.replace("{message}", "").replace("{bot_name}", "")
        if "{" in remainder or "}" in remainder:
            raise ValueError("Only {message} and {bot_name} placeholders are supported")
        return value


class AgentAppearance(APIModel):
    primary_color: str = "#146cf6"
    surface_color: str = "#f6f8fb"
    position: Literal["bottom-right", "bottom-left"] = "bottom-right"
    launcher_style: Literal["spark", "bubble", "avatar"] = "spark"
    welcome_title: str = Field(default="How can I help you?", max_length=120)
    welcome_message: str = Field(
        default="Ask a question and I'll find the most useful answer.", max_length=500
    )
    placeholder: str = Field(default="Ask me anything...", max_length=120)
    suggested_questions: list[str] = Field(default_factory=list, max_length=8)
    show_branding: bool = True
    widget_width: int = Field(default=380, ge=320, le=600)
    widget_height: int = Field(default=680, ge=480, le=900)
    page_margin: int = Field(default=24, ge=8, le=64)
    text_direction: Literal["ltr", "rtl"] = "ltr"
    elevated_shadow: bool = True
    open_on_page_load: bool = False
    font_family: Literal["Inter", "DM Sans", "Manrope", "System UI"] = "Inter"
    corner_radius: int = Field(default=24, ge=0, le=32)
    greeting_mode: Literal["always", "once", "interaction", "never"] = "once"
    interface_language: str = Field(default="English", min_length=2, max_length=60)
    detect_browser_language: bool = True
    translations: dict[str, str] = Field(
        default_factory=lambda: {
            "newConversation": "New conversation",
            "sendButton": "Send",
            "closeChat": "Close chat",
            "offlineMessage": "We'll be back soon",
        }
    )
    require_consent: bool = False
    consent_message: str = Field(
        default="I agree that my messages may be processed to answer my request.", max_length=500
    )
    privacy_policy_url: str = Field(default="", max_length=2000)
    widget_name: str = Field(default="", max_length=120)
    z_index: int = Field(default=99_999, ge=1, le=2_147_483_647)
    custom_domain: str = Field(default="", max_length=253)
    whatsapp: WhatsAppMessageSettings | None = None
    deployment_channel: Literal[
        "website", "whatsapp", "telegram", "instagram", "facebook", "slack", "teams", "api", "notion", "zapier"
    ] = "website"

    @field_validator("primary_color", "surface_color")
    @classmethod
    def valid_color(cls, value: str) -> str:
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
            raise ValueError("must be a six-digit hex color")
        return value.lower()


class AgentModelProfile(APIModel):
    provider: Literal["nvidia", "openai", "anthropic", "google", "ollama", "openai-compatible"] = "nvidia"
    model: str = "nvidia/nemotron-3-ultra-550b-a55b"
    connection_id: UUID | None = None
    internet_access: Literal["none", "allowlisted", "public"] = "none"
    temperature: float = Field(default=1, ge=0, le=2)
    top_p: float = Field(default=0.95, gt=0, le=1)
    max_tokens: int = Field(default=16_384, ge=64, le=32_768)
    enable_thinking: bool = True
    citation_mode: Literal["always", "when-available", "off"] = "when-available"
    # Retrieval tuning is persisted for the vectorless RAG pipeline but is an
    # internal control, not part of the public agent model contract.
    rerank_candidates: int = Field(default=60, ge=10, le=100, exclude=True)
    final_context_chunks: int = Field(default=8, ge=2, le=20, exclude=True)

    @field_validator("model")
    @classmethod
    def normalize_model_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or len(normalized) > 240:
            raise ValueError("model id is required and must be at most 240 characters")
        return normalized


class AgentSecurity(APIModel):
    allowed_domains: list[str] = Field(default_factory=lambda: ["localhost"], max_length=100)
    rate_limit_per_minute: int = Field(default=30, ge=1, le=10_000)
    collect_email: bool = False
    mask_sensitive_data: bool = True
    retention_days: int = Field(default=90, ge=1, le=3650)
    web_fallback: Literal["off", "related_only", "public"] = "off"
    web_allowed_domains: list[str] = Field(default_factory=list, max_length=50)
    blocked_topics: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("allowed_domains")
    @classmethod
    def normalize_domains(cls, values: list[str]) -> list[str]:
        domains: list[str] = []
        for raw in values:
            value = raw.lower().strip().removeprefix("https://").removeprefix("http://").split("/")[0]
            if not value or any(character.isspace() for character in value):
                raise ValueError("invalid allowed domain")
            domains.append(value)
        return sorted(set(domains))

    @field_validator("web_allowed_domains")
    @classmethod
    def normalize_web_domains(cls, values: list[str]) -> list[str]:
        domains: list[str] = []
        for raw in values:
            value = raw.lower().strip().removeprefix("https://").removeprefix("http://").split("/")[0]
            if not value or any(character.isspace() for character in value):
                raise ValueError("invalid web fallback domain")
            domains.append(value)
        return sorted(set(domains))

    @field_validator("blocked_topics")
    @classmethod
    def normalize_blocked_topics(cls, values: list[str]) -> list[str]:
        return sorted({value.strip() for value in values if value.strip()})


class AgentCreate(APIModel):
    name: str = Field(min_length=2, max_length=120)
    description: str = Field(default="", max_length=500)
    template: str | None = Field(default=None, max_length=80)
    tone: AgentTone = AgentTone.FRIENDLY
    language: str = Field(default="English", min_length=2, max_length=60)
    deployment_channel: Literal[
        "website", "whatsapp", "telegram", "instagram", "facebook", "slack", "teams", "api", "notion", "zapier"
    ] = "website"


class AgentDuplicate(APIModel):
    name: str = Field(min_length=2, max_length=120)
    deployment_channel: Literal[
        "website", "whatsapp", "telegram", "instagram", "facebook", "slack", "teams", "api", "notion", "zapier"
    ] = "website"


class AgentPatch(APIModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    instructions: str | None = Field(default=None, max_length=20_000)
    status: AgentStatus | None = None
    tone: AgentTone | None = None
    language: str | None = Field(default=None, max_length=60)
    avatar: str | None = Field(default=None, max_length=500)
    appearance: AgentAppearance | None = None
    model: AgentModelProfile | None = None
    security: AgentSecurity | None = None


class AgentOut(APIModel):
    id: UUID
    workspace_id: UUID
    public_id: str
    name: str
    description: str
    instructions: str
    status: AgentStatus
    tone: AgentTone
    language: str
    avatar: str
    conversations: int
    resolution_rate: float
    knowledge_count: int
    last_updated: datetime
    created_at: datetime
    appearance: AgentAppearance
    model: AgentModelProfile
    security: AgentSecurity


class EducationKnowledgeDestination(APIModel):
    course_id: UUID
    curriculum_id: UUID
    paper_id: UUID | None = None
    batch_id: UUID | None = None
    material_type: str = Field(default="notes", min_length=1, max_length=40)
    language: str = Field(default="English", min_length=1, max_length=80)


class KnowledgeCreate(APIModel):
    name: str = Field(min_length=1, max_length=240)
    kind: KnowledgeKind
    url: HttpUrl | None = None
    content: str | None = Field(default=None, max_length=2_000_000)
    object_key: str | None = Field(default=None, max_length=1000)
    education_destination: EducationKnowledgeDestination | None = None
    unassigned_inbox: bool = False

    @field_validator("content")
    @classmethod
    def reject_empty_content(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("content cannot be blank")
        return value


class KnowledgeOut(APIModel):
    id: UUID
    workspace_id: UUID
    agent_id: UUID
    name: str
    kind: KnowledgeKind
    status: KnowledgeStatus
    size_label: str
    chunks: int
    updated_at: datetime
    url: str | None = None
    content: str | None = None
    error: str | None = None
    extraction_issue_count: int = 0
    extraction_available: bool = False


class KnowledgeUntrain(APIModel):
    source_ids: list[UUID] = Field(min_length=1, max_length=100)

    @field_validator("source_ids")
    @classmethod
    def unique_source_ids(cls, values: list[UUID]) -> list[UUID]:
        if len(values) != len(set(values)):
            raise ValueError("source_ids must be unique")
        return values


class FactCreate(APIModel):
    question: str = Field(min_length=2, max_length=10_000)
    answer: str = Field(min_length=1, max_length=50_000)
    priority: int = Field(default=0, ge=-100, le=100)
    status: FactStatus = FactStatus.APPROVED


class FactPatch(APIModel):
    question: str | None = Field(default=None, min_length=2, max_length=10_000)
    answer: str | None = Field(default=None, min_length=1, max_length=50_000)
    priority: int | None = Field(default=None, ge=-100, le=100)
    status: FactStatus | None = None


class FactOut(APIModel):
    id: UUID
    source_id: UUID | None
    agent_id: UUID
    question: str
    answer: str
    status: FactStatus
    priority: int
    revision: int
    created_at: datetime
    updated_at: datetime


class JobOut(APIModel):
    id: UUID
    source_id: UUID
    status: JobStatus
    step: str
    progress: int
    attempts: int
    error: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class UploadPresignRequest(APIModel):
    filename: str = Field(min_length=1, max_length=240)
    content_type: Literal[
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "text/plain",
        "text/markdown",
        "image/png",
        "image/jpeg",
        "image/tiff",
    ]
    size_bytes: int = Field(gt=0)
    checksum_sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")

    @model_validator(mode="after")
    def validate_filename_type(self) -> UploadPresignRequest:
        extension = self.filename.lower().rsplit(".", 1)[-1] if "." in self.filename else ""
        expected = {
            "pdf": "application/pdf",
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "txt": "text/plain",
            "md": "text/markdown",
            "markdown": "text/markdown",
            "png": "image/png",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "tif": "image/tiff",
            "tiff": "image/tiff",
        }.get(extension)
        if not expected:
            raise ValueError(
                "filename must use a supported PDF, DOCX, TXT, Markdown, PNG, JPEG, or TIFF extension"
            )
        if self.content_type != expected:
            raise ValueError("contentType does not match the filename extension")
        return self


class UploadPresignOut(APIModel):
    method: Literal["POST"] = "POST"
    url: str
    object_key: str
    fields: dict[str, str]
    expires_at: datetime


class CitationOut(APIModel):
    title: str
    url: str | None = None


class MessageOut(APIModel):
    id: UUID
    role: MessageRole
    content: str
    created_at: datetime
    citations: list[CitationOut] = Field(default_factory=list)
    delivery_status: str | None = None
    message_format: dict[str, Any] | None = None


class VisitorDetails(APIModel):
    phone: str | None = Field(default=None, max_length=80)
    ip_address: str | None = Field(default=None, max_length=45)
    location: str | None = Field(default=None, max_length=500)
    timezone: str | None = Field(default=None, max_length=500)
    language: str | None = Field(default=None, max_length=500)
    page_slug: str | None = Field(default=None, max_length=500)
    utm_source: str | None = Field(default=None, max_length=240)
    utm_medium: str | None = Field(default=None, max_length=240)
    utm_campaign: str | None = Field(default=None, max_length=240)
    utm_term: str | None = Field(default=None, max_length=240)
    utm_content: str | None = Field(default=None, max_length=500)
    referrer: str | None = Field(default=None, max_length=2048)


class WhatsAppContactOut(APIModel):
    phone_number: str
    wa_id: str
    profile_name: str | None = None
    last_message_at: datetime | None = None
    last_message_type: str | None = None


class ConversationOut(APIModel):
    purpose: AgentPurpose = AgentPurpose.SUPPORT
    lead_id: UUID | None = None
    lead_status: str | None = None
    can_update_lead_status: bool = False
    page_url: str | None = None
    visitor_details: VisitorDetails = Field(default_factory=VisitorDetails)
    whatsapp_contact: WhatsAppContactOut | None = None
    id: UUID
    workspace_id: UUID
    agent_id: UUID
    visitor_name: str
    visitor_email: EmailStr | None = None
    channel: Channel
    state: ConversationState
    sentiment: Sentiment
    preview: str
    unread: int
    started_at: datetime
    updated_at: datetime
    messages: list[MessageOut] = Field(default_factory=list)


class ConversationResolve(APIModel):
    lead_status: LeadLifecycleStatus | None = None


class ConversationPatch(APIModel):
    visitor_email: EmailStr | None = None
    page_url: str | None = Field(default=None, max_length=2048)
    visitor_details: VisitorDetails | None = None
    state: ConversationState | None = None
    unread: int | None = Field(default=None, ge=0)
    visitor_name: str | None = Field(default=None, max_length=160)


class WhatsAppTemplateSelection(APIModel):
    name: str = Field(min_length=1, max_length=512, pattern=r"^[a-z0-9_]+$")
    language: str = Field(min_length=2, max_length=20, pattern=r"^[A-Za-z_]+$")
    parameters: list[str] = Field(default_factory=list, max_length=30)
    consent_confirmed: Literal[True]

    @field_validator("parameters")
    @classmethod
    def validate_parameters(cls, values: list[str]) -> list[str]:
        if any(not value.strip() or len(value) > 1024 for value in values):
            raise ValueError("Template parameters must contain 1 to 1024 characters")
        return values


class MessageButton(APIModel):
    id: str = Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9_-]+$")
    title: str = Field(min_length=1, max_length=20)


class MessageTable(APIModel):
    columns: list[str] = Field(min_length=1, max_length=5)
    rows: list[list[str]] = Field(min_length=1, max_length=20)

    @field_validator("columns")
    @classmethod
    def validate_columns(cls, values: list[str]) -> list[str]:
        if any(not value.strip() or len(value) > 40 for value in values):
            raise ValueError("Table columns must contain 1 to 40 characters")
        return values

    @field_validator("rows")
    @classmethod
    def validate_rows(cls, values: list[list[str]]) -> list[list[str]]:
        if any(not row or len(row) > 5 or any(len(cell) > 160 for cell in row) for row in values):
            raise ValueError("Table rows must contain 1 to 5 cells of up to 160 characters")
        return values


class MessageFormat(APIModel):
    type: Literal[
        "text",
        "buttons",
        "list",
        "table",
        "image",
        "video",
        "audio",
        "document",
        "sticker",
        "location",
        "contact",
        "cta_url",
        "flow",
        "product",
        "product_list",
        "catalog",
    ] = "text"
    buttons: list[MessageButton] = Field(default_factory=list, max_length=3)
    table: MessageTable | None = None
    config: dict[str, Any] = Field(default_factory=dict)


class ConversationReplyCreate(APIModel):
    whatsapp_template: WhatsAppTemplateSelection | None = None
    message_format: MessageFormat | None = None
    content: str = Field(min_length=1, max_length=12_000)


T = TypeVar("T")


class PageResult(APIModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


class ChatStreamRequest(APIModel):
    agent_id: UUID | str
    message: str = Field(min_length=1, max_length=12_000)
    conversation_id: UUID | str | None = None
    visitor_id: str | None = Field(default=None, max_length=128)
    idempotency_key: str | None = Field(default=None, max_length=128)


class LeadCreate(APIModel):
    agent_id: UUID
    conversation_id: UUID | None = None
    name: str | None = Field(default=None, max_length=160)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=80)
    consent: bool = False
    fields: dict[str, Any] = Field(default_factory=dict)


class LeadPatch(APIModel):
    status: str = Field(min_length=1, max_length=40)


class LeadOut(APIModel):
    id: UUID
    workspace_id: UUID
    agent_id: UUID
    conversation_id: UUID | None
    name: str | None
    email: EmailStr | None
    phone: str | None
    status: str
    consent: bool
    fields: dict[str, Any]
    created_at: datetime
    updated_at: datetime


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


class AnalyticsSummary(APIModel):
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


class IntegrationOut(APIModel):
    id: str
    name: str
    description: str
    category: Literal["channel", "automation", "data", "developer"]
    icon: str
    connected: bool
    coming_soon: bool = False


class IntegrationPatch(APIModel):
    connected: bool


class WhatsAppConnectionOut(APIModel):
    id: UUID | None = None
    business_account_id: UUID | None = None
    waba_id: str
    phone_number_id: str
    display_phone_number: str
    verified_name: str
    agent_id: UUID | None
    status: str
    token_expires_at: datetime | None = None
    connected_at: datetime


class WhatsAppStatusOut(APIModel):
    enabled: bool
    connected: bool
    connection: WhatsAppConnectionOut | None = None
    connections: list[WhatsAppConnectionOut] = Field(default_factory=list)


class WhatsAppBootstrapOut(WhatsAppStatusOut):
    webhook_url: str = ""
    missing_settings: list[str] = Field(default_factory=list)
    app_id: str | None = None
    configuration_id: str | None = None
    api_version: str
    signup_session: str | None = None


class WhatsAppCompleteRequest(APIModel):
    signup_session: str = Field(min_length=20, max_length=4096)
    code: str = Field(min_length=8, max_length=4096)
    waba_id: str = Field(min_length=1, max_length=80, pattern=r"^[0-9]+$")
    phone_number_id: str = Field(min_length=1, max_length=80, pattern=r"^[0-9]+$")
    agent_id: UUID
    two_step_verification_pin: str = Field(pattern=r"^[0-9]{6}$")


class WidgetBootstrap(APIModel):
    agent_id: UUID
    public_id: str
    name: str
    avatar: str
    language: str
    appearance: AgentAppearance
    collect_email: bool
    session_endpoint: str
    stream_endpoint: str


class WidgetSessionCreate(APIModel):
    visitor_details: VisitorDetails = Field(default_factory=VisitorDetails)
    visitor_id: str | None = Field(default=None, max_length=128)
    visitor_name: str | None = Field(default=None, max_length=160)
    visitor_email: EmailStr | None = None
    page_url: str | None = Field(default=None, max_length=2048)


class WidgetSessionOut(APIModel):
    conversation_id: UUID
    conversation_public_id: str
    session_token: str
    expires_at: datetime


class WidgetMessageRequest(APIModel):
    message: str = Field(min_length=1, max_length=12_000)
    idempotency_key: str | None = Field(default=None, max_length=128)


class FeedbackCreate(APIModel):
    value: Literal[-1, 1]
    reason: str | None = Field(default=None, max_length=500)


class OpenAIMessage(APIModel):
    role: Literal["user", "assistant", "system"]
    content: str = Field(max_length=50_000)


class OpenAICompletionRequest(APIModel):
    model: str
    messages: list[OpenAIMessage] = Field(min_length=1, max_length=100)
    stream: bool = False
    user: str | None = None


class DailyHealthOut(APIModel):
    day: date
    conversations: int
    resolved: int
    escalated: int
    average_response_seconds: float
