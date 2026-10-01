export type AgentStatus = 'active' | 'draft' | 'training' | 'error';
export type AgentTone = 'professional' | 'friendly' | 'concise' | 'empathetic' | 'playful';
export type AgentPurpose = 'support' | 'lead_generation' | 'education';
export type DeploymentChannel = 'website' | 'whatsapp' | 'telegram' | 'instagram' | 'facebook' | 'slack' | 'teams' | 'api' | 'notion' | 'zapier';
export type KnowledgeKind = 'file' | 'url' | 'text' | 'sitemap';
export type KnowledgeStatus = 'ready' | 'processing' | 'needs_review' | 'failed';

export interface User {
  id: string;
  name: string;
  email: string;
  role: 'owner' | 'admin' | 'billing_admin' | 'security_admin' | 'member' | 'analyst';
  emailVerified?: boolean;
  avatarUrl?: string;
}

export interface Session {
  accessToken: string;
  refreshToken?: string;
  user: User;
  expiresAt: string;
  impersonation?: {
    id: string;
    platformActorId: string;
    actingAsUserId: string;
  };
}

export interface WhatsAppMessageSettings {
  welcomeEnabled: boolean;
  welcomeMessage: string | null;
  replyTemplate: string;
}

export interface AgentAppearance {
  primaryColor: string;
  surfaceColor: string;
  position: 'bottom-right' | 'bottom-left';
  launcherStyle: 'spark' | 'bubble' | 'avatar';
  welcomeTitle: string;
  welcomeMessage: string;
  placeholder: string;
  suggestedQuestions: string[];
  showBranding: boolean;
  widgetWidth?: number;
  widgetHeight?: number;
  pageMargin?: number;
  textDirection?: 'ltr' | 'rtl';
  elevatedShadow?: boolean;
  openOnPageLoad?: boolean;
  fontFamily?: 'Inter' | 'DM Sans' | 'Manrope' | 'System UI';
  cornerRadius?: number;
  greetingMode?: 'always' | 'once' | 'interaction' | 'never';
  interfaceLanguage?: string;
  detectBrowserLanguage?: boolean;
  translations?: {
    newConversation: string;
    sendButton: string;
    closeChat: string;
    offlineMessage: string;
  };
  requireConsent?: boolean;
  consentMessage?: string;
  privacyPolicyUrl?: string;
  widgetName?: string;
  zIndex?: number;
  customDomain?: string;
  deploymentChannel?: DeploymentChannel;
  whatsapp?: WhatsAppMessageSettings | null;
}

export interface AgentModel {
  provider: 'nvidia' | 'openai' | 'anthropic' | 'google' | 'ollama' | 'openai-compatible';
  model: string;
  connectionId?: string | null;
  internetAccess?: 'none' | 'allowlisted' | 'public';
  temperature: number;
  topP: number;
  maxTokens: number;
  enableThinking: boolean;
  citationMode: 'always' | 'when-available' | 'off';
  rerankCandidates?: number;
  finalContextChunks?: number;
}

export interface AgentSecurity {
  allowedDomains: string[];
  rateLimitPerMinute: number;
  collectEmail: boolean;
  maskSensitiveData: boolean;
  retentionDays: number;
  webFallback?: 'off' | 'related_only' | 'public';
  webAllowedDomains?: string[];
  blockedTopics?: string[];
}

export interface Agent {
  whatsappNumber?: string | null;
  id: string;
  workspaceId?: string;
  publicId: string;
  name: string;
  description: string;
  instructions: string;
  status: AgentStatus;
  purpose?: AgentPurpose;
  tone: AgentTone;
  language: string;
  avatar: string;
  conversations: number;
  resolutionRate: number;
  knowledgeCount: number;
  lastUpdated: string;
  createdAt: string;
  appearance: AgentAppearance;
  model: AgentModel;
  security: AgentSecurity;
}

export interface KnowledgeSource {
  id: string;
  workspaceId?: string;
  agentId: string;
  name: string;
  kind: KnowledgeKind;
  status: KnowledgeStatus;
  sizeLabel: string;
  chunks: number;
  updatedAt: string;
  url?: string;
  content?: string;
  error?: string;
  extractionIssueCount?: number;
  extractionAvailable?: boolean;
}

export type ConversationState = 'open' | 'resolved' | 'escalated';

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'agent' | 'system';
  content: string;
  createdAt: string;
  citations?: Array<{ title: string; url?: string }>;
  deliveryStatus?: 'pending' | 'sent' | 'delivered' | 'read' | 'failed' | 'unknown' | null;
  messageFormat?: {
    type: 'text' | 'buttons' | 'list' | 'table' | 'image' | 'video' | 'audio' | 'document' | 'sticker' | 'location' | 'contact' | 'cta_url' | 'flow' | 'product' | 'product_list' | 'catalog';
    body?: string;
    buttons?: Array<{ id: string; title: string }>;
    table?: { columns: string[]; rows: string[][] };
    config?: Record<string, unknown>;
  } | null;
}

export interface Conversation {
  whatsappContact?: {
    phoneNumber: string;
    waId: string;
    profileName?: string | null;
    lastMessageAt?: string | null;
    lastMessageType?: string | null;
  } | null;
  purpose?: 'education' | 'support' | 'lead_generation';
  leadId?: string | null;
  leadStatus?: string | null;
  canUpdateLeadStatus?: boolean;
  pageUrl?: string | null;
  visitorDetails?: Record<string, string | null>;
  id: string;
  workspaceId?: string;
  agentId: string;
  visitorName: string;
  visitorEmail?: string;
  channel: 'widget' | 'api' | 'slack' | 'whatsapp';
  state: ConversationState;
  sentiment: 'positive' | 'neutral' | 'negative';
  preview: string;
  unread: number;
  startedAt: string;
  updatedAt: string;
  messages: ChatMessage[];
}

export interface AnalyticsSummary {
  period: string;
  conversations: number;
  conversationsDelta: number;
  resolutionRate: number;
  resolutionDelta: number;
  avgResponseSeconds: number;
  satisfaction: number;
  chart: Array<{ label: string; conversations: number; resolved: number }>;
  topQuestions: Array<{ question: string; count: number; resolutionRate: number }>;
  channels: Array<{ channel: string; value: number }>;
  // Optional for compatibility with previews or older API responses. The current
  // backend always supplies these domain summaries.
  agents?: {
    total: number;
    active: number;
    support: number;
    leadGeneration: number;
    education: number;
  };
  leads?: {
    created: number;
    qualified: number;
    converted: number;
    qualificationRate: number;
    conversionRate: number;
  };
  crm?: {
    deliveries: number;
    verified: number;
    failed: number;
    successRate: number;
  };
  education?: {
    students: number;
    activeEnrollments: number;
    conversations: number;
    activityEvents: number;
  };
}

export interface Integration {
  id: string;
  name: string;
  description: string;
  category: 'channel' | 'automation' | 'data' | 'developer';
  icon: string;
  connected: boolean;
  comingSoon?: boolean;
}

export interface WhatsAppAccount { id: string; name: string; appId: string; wabaId: string; status: string; webhookUrl: string }

export interface WhatsAppConnection {
  id?: string;
  businessAccountId?: string | null;
  wabaId: string;
  phoneNumberId: string;
  displayPhoneNumber: string;
  verifiedName: string;
  agentId: string | null;
  status: string;
  tokenExpiresAt?: string | null;
  connectedAt: string;
}

export interface WhatsAppBootstrap {
  webhookUrl?: string;
  missingSettings?: string[];
  appId: string | null;
  configurationId: string | null;
  signupSession: string | null;
  apiVersion: string;
  enabled: boolean;
  connected: boolean;
  connection: WhatsAppConnection | null;
  connections?: WhatsAppConnection[];
}

export interface WhatsAppStatus {
  enabled: boolean;
  connected: boolean;
  connection: WhatsAppConnection | null;
  connections?: WhatsAppConnection[];
}

export interface CompleteWhatsAppSignupInput {
  code: string;
  wabaId: string;
  phoneNumberId: string;
  agentId: string;
  signupSession: string;
  twoStepVerificationPin: string;
}

export interface Lead {
  id: string;
  workspaceId?: string;
  agentId: string;
  conversationId?: string;
  name?: string;
  email?: string;
  phone?: string;
  status: string;
  consent: boolean;
  fields: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
}

export interface PageResult<T> {
  items: T[];
  total: number;
  page: number;
  pageSize: number;
}

export interface ChatStreamRequest {
  agentId: string;
  message: string;
  conversationId?: string;
  visitorId?: string;
}

export interface WidgetBootstrap {
  agentId: string;
  publicId: string;
  name: string;
  avatar: string;
  language?: string;
  appearance: AgentAppearance;
  collectEmail: boolean;
  sessionEndpoint: string;
  streamEndpoint: string;
}

export interface WidgetSession {
  conversationId: string;
  conversationPublicId: string;
  sessionToken: string;
  expiresAt: string;
}

export interface WidgetInitMessage {
  type: 'northstar:init';
  agentId: string;
  bootstrap: WidgetBootstrap;
  session: WidgetSession;
}

export interface WidgetReadyMessage {
  type: 'northstar:ready';
  agentId: string;
}

export interface WidgetSessionRequestMessage {
  type: 'northstar:session-request';
  agentId: string;
  requestId: string;
}

export interface WidgetSessionMessage {
  type: 'northstar:session';
  agentId: string;
  requestId: string;
  session: WidgetSession;
}

export interface WidgetSessionErrorMessage {
  type: 'northstar:session-error';
  agentId: string;
  requestId: string;
  message: string;
}

export type ChatStreamEvent =
  | { type: 'start'; conversationId: string; messageId: string }
  | { type: 'user_translation'; content: string }
  | { type: 'token'; content: string }
  | { type: 'citation'; title: string; url?: string }
  | { type: 'done'; conversationId: string }
  | { type: 'error'; message: string };

export interface CreateAgentInput {
  whatsappConnectionId?: string;
  name: string;
  description: string;
  template?: string;
  purpose?: AgentPurpose;
  tone?: AgentTone;
  language?: string;
  deploymentChannel?: DeploymentChannel;
}

export interface DuplicateAgentInput {
  name: string;
  deploymentChannel: DeploymentChannel;
}

export type AgentPatch = Partial<Omit<Agent, 'id' | 'createdAt'>>;
