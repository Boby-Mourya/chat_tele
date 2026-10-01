import { knowledgeFileSizeError } from '@/lib/upload-limits';
import { demoAgents, demoAnalytics, demoConversations, demoIntegrations, demoKnowledge, demoLeads } from '@/lib/demo-data';
import { clone, readStorage, writeStorage } from '@/lib/storage';
import { localizeAgentAppearance } from '@/lib/widget-localization';
import { activeWorkspaceId } from '@/lib/workspace-api';
import type {
  Agent, AgentPatch, AnalyticsSummary, ChatStreamEvent, ChatStreamRequest, Conversation, ConversationState,
  CompleteWhatsAppSignupInput, CreateAgentInput, DuplicateAgentInput, Integration, KnowledgeKind, KnowledgeSource, Lead, PageResult, Session,
  WhatsAppBootstrap, WhatsAppConnection, WhatsAppStatus, WidgetBootstrap, WidgetSession,
} from '@/types';

const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? '/api/v1';
const DEMO_MODE = (import.meta.env.VITE_DEMO_MODE as string | undefined) === 'true';
const TOKEN_KEY = 'northstar.session';
const AGENTS_KEY = 'northstar.agents';
const KNOWLEDGE_KEY = 'northstar.knowledge';
const CONVERSATIONS_KEY = 'northstar.conversations';
const LEADS_KEY = 'northstar.leads';
const INTEGRATIONS_KEY = 'northstar.integrations';
export const AUTH_SESSION_EVENT = 'northstar:session-changed';

interface ApiRequestInit extends RequestInit {
  skipAuth?: boolean;
  skipRefresh?: boolean;
}

let refreshFlight: { token: string; promise: Promise<Session> } | null = null;

export class ApiError extends Error {
  constructor(message: string, readonly status: number, readonly detail?: unknown) { super(message); this.name = 'ApiError'; }
}

const pause = (ms = 220) => new Promise((resolve) => setTimeout(resolve, ms));
const id = (prefix: string) => `${prefix}-${crypto.randomUUID?.() ?? Math.random().toString(36).slice(2)}`;

function session(): Session | null {
  const saved = readStorage<Session | null>(TOKEN_KEY, null);
  // A demo token cannot authenticate against the real backend after a deployment switch.
  return !DEMO_MODE && saved?.accessToken.startsWith('demo.') ? null : saved;
}

function notifySessionChanged(): void {
  window.dispatchEvent(new Event(AUTH_SESSION_EVENT));
}

function browserSession(value: Session): Session {
  const safe = { ...value };
  delete safe.refreshToken;
  return safe;
}

function persistSession(value: Session): Session {
  const safe = browserSession(value);
  writeStorage(TOKEN_KEY, safe);
  notifySessionChanged();
  return safe;
}

function clearSession(expectedCredential?: string): void {
  const current = session();
  if (
    expectedCredential
    && current?.refreshToken !== expectedCredential
    && current?.accessToken !== expectedCredential
  ) return;
  localStorage.removeItem(TOKEN_KEY);
  notifySessionChanged();
}

async function refreshSession(active: Session): Promise<Session> {
  const refreshToken = active.refreshToken;
  const refreshIdentity = refreshToken ?? `http-only-cookie:${active.accessToken}`;
  if (refreshFlight?.token === refreshIdentity) return refreshFlight.promise;

  const promise = (async () => {
    try {
      const response = await fetch(`${API_URL}/auth/refresh`, {
        method: 'POST',
        credentials: 'include',
        headers: { Accept: 'application/json', ...(refreshToken ? { 'Content-Type': 'application/json' } : {}) },
        body: refreshToken ? JSON.stringify({ refreshToken }) : undefined,
      });
      if (!response.ok) throw new ApiError('Your session has expired. Please sign in again.', 401);
      const rotated = await response.json() as Session;
      const current = session();
      const stillCurrent = refreshToken
        ? current?.refreshToken === refreshToken
        : current?.accessToken === active.accessToken;
      if (!current || !stillCurrent) {
        if (current) return current;
        throw new ApiError('Your session has expired. Please sign in again.', 401);
      }
      return persistSession(rotated);
    } catch (error) {
      clearSession(refreshToken ?? active.accessToken);
      if (error instanceof ApiError) throw error;
      throw new ApiError('Your session has expired. Please sign in again.', 401, error);
    }
  })();

  refreshFlight = { token: refreshIdentity, promise };
  try {
    return await promise;
  } finally {
    if (refreshFlight?.promise === promise) refreshFlight = null;
  }
}

export async function request<T>(path: string, options: ApiRequestInit = {}): Promise<T> {
  const { skipAuth = false, skipRefresh = false, ...init } = options;
  const active = session();
  const workspaceId = activeWorkspaceId();
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    credentials: init.credentials ?? 'include',
    headers: { Accept: 'application/json', ...(init.body ? { 'Content-Type': 'application/json' } : {}), ...(!skipAuth && active ? { Authorization: `Bearer ${active.accessToken}` } : {}), ...(!skipAuth && workspaceId ? { 'X-Workspace-ID': workspaceId } : {}), ...init.headers },
  });
  if (response.status === 401 && !skipAuth && !skipRefresh && active) {
    await refreshSession(active);
    return request<T>(path, { ...init, skipRefresh: true });
  }
  if (!response.ok) {
    let rawBody = '';
    try { rawBody = await response.text(); } catch { /* Preserve the HTTP status even if the body stream fails. */ }
    let detail: unknown = rawBody || undefined;
    if (rawBody) {
      try { detail = JSON.parse(rawBody) as unknown; } catch { /* Plain-text proxy and upstream errors remain readable. */ }
    }
    throw new ApiError(`Request failed (${response.status})`, response.status, detail);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

async function requestEvidence(path: string, retried = false): Promise<Blob> {
  const active = session();
  const workspaceId = activeWorkspaceId();
  const response = await fetch(`${API_URL}${path}`, {
    credentials: 'include',
    headers: {
      ...(active ? { Authorization: `Bearer ${active.accessToken}` } : {}),
      ...(workspaceId ? { 'X-Workspace-ID': workspaceId } : {}),
    },
  });
  if (response.status === 401 && active && !retried) {
    await refreshSession(active);
    return requestEvidence(path, true);
  }
  if (!response.ok) throw new ApiError(`Evidence request failed (${response.status})`, response.status);
  return response.blob();
}

export interface ExtractionReading {
  kind: string;
  text: string;
  complete: boolean;
  blank?: boolean;
  uncertain?: boolean;
  cells?: Array<{ row: number; column: number; text: string; row_span?: number; column_span?: number; state?: string; header?: boolean; header_refs?: string[]; unit?: string | null }>;
  [key: string]: unknown;
}

export interface ExtractionBlock {
  id: string;
  type: string;
  status: string;
  native_text: string;
  selected_text: string | null;
  visual: ExtractionReading | null;
  reviewed_structure?: ExtractionReading;
  related_block_ids?: string[];
  bbox_px?: number[];
  crop?: string;
}

export interface ExtractionPage {
  number: number;
  native_text: string;
  visual_text: string | null;
  selected_text: string | null;
  image: string | null;
  source_unit?: string;
  printed_page_label?: string | null;
  blocks: ExtractionBlock[];
  requires_second_review?: boolean;
  primary_review?: { reviewer: string; reviewed_at: string };
  second_review?: { reviewer: string; reviewed_at: string };
  requires_review?: boolean;
  quality?: { score: number; method: string; reasons: string[]; native_character_count: number; native_word_count: number; native_figure_count: number; native_table_count: number; formula_detected: boolean };
}

export interface ExtractionRecord {
  schema_version: number;
  extraction_revision: number;
  source_sha256: string;
  review_status: string;
  pages: ExtractionPage[];
  issues: Array<{ id: string; page: number; code: string; message: string; status?: string; technical?: boolean; block_id?: string | null }>;
  checks: Array<{ name: string; status: string; details: string[] }>;
  release_blockers: string[];
  word?: { blocks: unknown[]; channels: unknown[] };
}

export interface ExtractionReviewSubmission {
  extractionRevision: number;
  pages: Array<{ number: number; selectedText: string; reason: string; structureConfirmed: boolean; blankConfirmed: boolean;
    blocks: Array<{ id: string; selectedText: string; structure: ExtractionReading; relatedBlockIds: string[] }> }>;
  issueResolutions: Array<{ id: string; action: 'source_verified' | 'source_anomaly' | 'unresolved'; reason: string }>;
}

async function withFallback<T>(remote: () => Promise<T>, fallback: () => Promise<T>): Promise<T> {
  if (DEMO_MODE) {
    try { return await remote(); } catch (error) {
      // Preserve actionable validation/auth failures from a running API. A 404 is
      // allowed to fall back because standalone Vite previews have no API route.
      if (error instanceof ApiError && [400, 401, 403, 409, 422].includes(error.status)) throw error;
      return fallback();
    }
  }
  return remote();
}

function demoAgentList(): Agent[] { return readStorage(AGENTS_KEY, clone(demoAgents)); }
function demoKnowledgeList(): KnowledgeSource[] { return readStorage(KNOWLEDGE_KEY, clone(demoKnowledge)); }
function demoConversationList(): Conversation[] { return readStorage(CONVERSATIONS_KEY, clone(demoConversations)); }
function demoLeadList(): Lead[] { return readStorage(LEADS_KEY, clone(demoLeads)); }
function demoIntegrationList(): Integration[] {
  const saved = readStorage<Integration[]>(INTEGRATIONS_KEY, []);
  const states = new Map(saved.map((item) => [item.id, item.connected]));
  return clone(demoIntegrations).map((item) => ({ ...item, connected: states.get(item.id) ?? item.connected }));
}

interface UploadPresignResponse {
  method: 'POST';
  url: string;
  objectKey: string;
  fields: Record<string, string>;
  expiresAt: string;
}

function uploadContentType(file: File): string {
  const extension = file.name.toLowerCase().split('.').pop();
  if (extension === 'pdf') return 'application/pdf';
  if (extension === 'docx') return 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';
  if (extension === 'md' || extension === 'markdown') return 'text/markdown';
  if (extension === 'png') return 'image/png';
  if (extension === 'jpg' || extension === 'jpeg') return 'image/jpeg';
  if (extension === 'tif' || extension === 'tiff') return 'image/tiff';
  return 'text/plain';
}

async function uploadKnowledgeFile(file: File): Promise<string> {
  const sizeError = knowledgeFileSizeError(file);
  if (sizeError) throw new ApiError(sizeError, 413);
  const contentType = uploadContentType(file);
  const digest = await crypto.subtle.digest('SHA-256', await new Response(file).arrayBuffer());
  const checksumSha256 = Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('');
  const presign = await request<UploadPresignResponse>('/uploads/presign', {
    method: 'POST',
    body: JSON.stringify({ filename: file.name, contentType, sizeBytes: file.size, checksumSha256 }),
  });
  const form = new FormData();
  for (const [name, value] of Object.entries(presign.fields)) form.append(name, value);
  form.append('file', file);
  const uploaded = await fetch(presign.url, {
    method: presign.method,
    body: form,
  });
  if (!uploaded.ok) throw new ApiError(`File upload failed (${uploaded.status})`, uploaded.status);
  return presign.objectKey;
}

async function* parseChatEvents(response: Response): AsyncGenerator<ChatStreamEvent> {
  if (!response.ok || !response.body) throw new ApiError('Unable to start chat', response.status);
  const reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = '';
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const frames = buffer.split('\n\n'); buffer = frames.pop() ?? '';
    for (const frame of frames) {
      const data = frame.split('\n').filter((line) => line.startsWith('data:')).map((line) => line.slice(5).trim()).join('\n');
      if (!data || data === '[DONE]') continue;
      yield JSON.parse(data) as ChatStreamEvent;
    }
  }
}

async function* demoChatEvents(question: string, currentConversationId?: string, signal?: AbortSignal, language = 'English'): AsyncGenerator<ChatStreamEvent> {
  const conversationId = currentConversationId ?? id('conv');
  yield { type: 'start', conversationId, messageId: id('msg') };
  yield { type: 'user_translation', content: demoDisplayQuestion(question, language) };
  const answer = demoAnswer(question, language);
  for (const word of answer.split(' ')) {
    if (signal?.aborted) return;
    await pause(24 + Math.random() * 28);
    yield { type: 'token', content: `${word} ` };
  }
  yield { type: 'citation', title: 'Northstar knowledge base' };
  yield { type: 'done', conversationId };
}

export function agentFromWidgetBootstrap(value: WidgetBootstrap): Agent {
  const now = new Date().toISOString();
  const language = value.language ?? value.appearance.interfaceLanguage ?? 'English';
  const appearance = value.appearance.interfaceLanguage === language ? value.appearance : localizeAgentAppearance(value.appearance, language);
  return {
    id: value.agentId, publicId: value.publicId, name: value.name, avatar: value.avatar,
    description: 'Grounded AI assistant', instructions: '', status: 'active', tone: 'friendly', language,
    conversations: 0, resolutionRate: 0, knowledgeCount: 0, createdAt: now, lastUpdated: now,
    appearance,
    model: { provider: 'nvidia', model: 'nvidia/nemotron-3-ultra-550b-a55b', temperature: 1, topP: 0.95, maxTokens: 16384, enableThinking: true, citationMode: 'when-available' },
    security: { allowedDomains: [], rateLimitPerMinute: 30, collectEmail: value.collectEmail, maskSensitiveData: true, retentionDays: 90 },
  };
}

export const api = {
  auth: {
    session,
    adopt(value: Session): Session { return persistSession(value); },
    async login(email: string, password: string): Promise<Session> {
      const result = await withFallback(() => request<Session>('/auth/login', { method: 'POST', body: JSON.stringify({ email, password }), skipAuth: true, skipRefresh: true }), async () => {
        await pause(450);
        if (!email.trim() || !password) throw new ApiError('Email and password are required.', 400);
        const result: Session = { accessToken: `demo.${btoa(email)}.token`, expiresAt: new Date(Date.now() + 86_400_000).toISOString(), user: { id: 'user-demo', name: email.split('@')[0]?.replace(/[._-]/g, ' ') || 'Northstar User', email, role: 'owner' } };
        return result;
      });
      return persistSession(result);
    },
    async logout(): Promise<void> {
      const active = session();
      const revoke = (value: Session | null) => request('/auth/logout', {
        method: 'POST',
        body: value?.refreshToken ? JSON.stringify({ refreshToken: value.refreshToken }) : undefined,
        skipRefresh: true,
      });
      try {
        if (!DEMO_MODE) {
          try {
            await revoke(active);
          } catch (error) {
            if (!(error instanceof ApiError) || error.status !== 401 || !active) throw error;
            await revoke(await refreshSession(active));
          }
        }
      } finally {
        clearSession();
      }
    },
  },
  agents: {
    list: () => withFallback(() => request<Agent[]>('/agents'), async () => { await pause(); return demoAgentList(); }),
    get: (agentId: string) => withFallback(() => request<Agent>(`/agents/${agentId}`), async () => { await pause(100); const found = demoAgentList().find((item) => item.id === agentId); if (!found) throw new ApiError('Agent not found', 404); return found; }),
    create: (input: CreateAgentInput) => withFallback(() => request<Agent>('/agents', { method: 'POST', body: JSON.stringify(input) }), async () => {
      await pause(); const base = clone(demoAgents[0]!); const createdId = id('agent'); const language = input.language ?? 'English'; const created: Agent = { ...base, id: createdId, publicId: id('public'), name: input.name, description: input.description, instructions: templateInstructions(input.template), tone: input.tone ?? 'friendly', language, status: 'draft', conversations: 0, resolutionRate: 0, knowledgeCount: 0, createdAt: new Date().toISOString(), lastUpdated: new Date().toISOString(), appearance: { ...localizeAgentAppearance(base.appearance, language), deploymentChannel: input.deploymentChannel ?? 'website' } };
      const items = demoAgentList(); items.unshift(created); writeStorage(AGENTS_KEY, items); return created;
    }),
    duplicate: (agentId: string, input: DuplicateAgentInput) => withFallback(() => request<Agent>(`/agents/${agentId}/duplicate`, { method: 'POST', body: JSON.stringify(input) }), async () => {
      await pause(); const source = demoAgentList().find((item) => item.id === agentId); if (!source) throw new ApiError('Agent not found', 404);
      const created: Agent = { ...clone(source), id: id('agent'), publicId: id('public'), name: input.name, status: 'draft', conversations: 0, resolutionRate: 0, knowledgeCount: 0, createdAt: new Date().toISOString(), lastUpdated: new Date().toISOString(), appearance: { ...clone(source.appearance), deploymentChannel: input.deploymentChannel } };
      const items = demoAgentList(); items.unshift(created); writeStorage(AGENTS_KEY, items); return created;
    }),
    update: (agentId: string, patch: AgentPatch) => withFallback(() => request<Agent>(`/agents/${agentId}`, { method: 'PATCH', body: JSON.stringify(patch) }), async () => {
      await pause(); const items = demoAgentList(); const index = items.findIndex((item) => item.id === agentId); if (index < 0) throw new ApiError('Agent not found', 404);
      const updated = { ...items[index]!, ...patch, lastUpdated: new Date().toISOString() }; items[index] = updated; writeStorage(AGENTS_KEY, items); return updated;
    }),
    remove: (agentId: string) => withFallback(() => request<void>(`/agents/${agentId}`, { method: 'DELETE' }), async () => { await pause(); writeStorage(AGENTS_KEY, demoAgentList().filter((item) => item.id !== agentId)); }),
  },
  feedback: (
  messageId: string,
  value: 1 | -1,
  reason?: string,
) =>
  request<void>(`/messages/${messageId}/feedback`, {
    method: 'POST',
    body: JSON.stringify({
      value,
      reason,
    }),
  }),
  knowledge: {
    list: (agentId: string) => withFallback(() => request<KnowledgeSource[]>(`/agents/${agentId}/knowledge`), async () => { await pause(); return demoKnowledgeList().filter((item) => item.agentId === agentId); }),
    extraction: (sourceId: string) => request<ExtractionRecord>(`/knowledge/${sourceId}/extraction`),
    extractionPage: (sourceId: string, page: number) => requestEvidence(`/knowledge/${sourceId}/extraction/pages/${page}`),
    extractionRegion: (sourceId: string, blockId: string) => requestEvidence(`/knowledge/${sourceId}/extraction/regions/${encodeURIComponent(blockId)}`),
    extractionArchive: (sourceId: string) => requestEvidence(`/knowledge/${sourceId}/extraction/archive`),
    extractionSourcePdf: (sourceId: string) => requestEvidence(`/knowledge/${sourceId}/extraction/source-pdf`),
    extractionText: (sourceId: string) => requestEvidence(`/knowledge/${sourceId}/extraction/text`),
    retryExtraction: (sourceId: string) => request<KnowledgeSource>(`/knowledge/${sourceId}/extraction/retry`, { method: 'POST' }),
    approveExtraction: (sourceId: string, submission: ExtractionReviewSubmission) => request<KnowledgeSource>(`/knowledge/${sourceId}/extraction/approve`, { method: 'POST', body: JSON.stringify(submission) }),
    add: (agentId: string, input: { name: string; kind: KnowledgeKind; url?: string; content?: string; file?: File }) => withFallback(async () => {
      const objectKey = input.file ? await uploadKnowledgeFile(input.file) : undefined;
      return request<KnowledgeSource>(`/agents/${agentId}/knowledge`, {
        method: 'POST',
        body: JSON.stringify({ name: input.name, kind: input.kind, url: input.url, content: input.content, objectKey }),
      });
    }, async () => {
      await pause(500); const source: KnowledgeSource = { id: id('ks'), agentId, name: input.name, kind: input.kind, url: input.url, content: input.content, status: 'ready', sizeLabel: input.kind === 'url' || input.kind === 'sitemap' ? '1 page' : input.kind === 'text' ? `${input.content?.split(/\s+/).length ?? 0} words` : input.file ? `${(input.file.size / 1_048_576).toFixed(1)} MB` : 'Uploaded', chunks: Math.max(1, Math.round((input.content?.length ?? input.file?.size ?? 700) / 600)), updatedAt: new Date().toISOString() };
      const items = demoKnowledgeList(); items.unshift(source); writeStorage(KNOWLEDGE_KEY, items); return source;
    }),
    remove: (sourceId: string) => withFallback(() => request<void>(`/knowledge/${sourceId}`, { method: 'DELETE' }), async () => { await pause(); writeStorage(KNOWLEDGE_KEY, demoKnowledgeList().filter((item) => item.id !== sourceId)); }),
    untrain: (sourceIds: string[]) => withFallback(() => request<{ removedSources: number; removedChunks: number }>('/knowledge/untrain', { method: 'POST', body: JSON.stringify({ sourceIds }) }), async () => { await pause(); const ids = new Set(sourceIds); const current = demoKnowledgeList(); const removed = current.filter((item) => ids.has(item.id)); writeStorage(KNOWLEDGE_KEY, current.filter((item) => !ids.has(item.id))); return { removedSources: removed.length, removedChunks: removed.reduce((sum, item) => sum + item.chunks, 0) }; }),
  },
  conversations: {
    list: () => withFallback(() => request<PageResult<Conversation>>('/conversations'), async () => { await pause(); const items = demoConversationList(); return { items, total: items.length, page: 1, pageSize: 50 }; }),
    updateState: (conversationId: string, state: ConversationState) => withFallback(() => request<Conversation>(`/conversations/${conversationId}`, { method: 'PATCH', body: JSON.stringify({ state }) }), async () => { const items = demoConversationList(); const item = items.find((entry) => entry.id === conversationId); if (!item) throw new ApiError('Conversation not found', 404); item.state = state; writeStorage(CONVERSATIONS_KEY, items); return item; }),
    reply: (conversationId: string, content: string, messageFormat?: import('@/types').ChatMessage['messageFormat']) => withFallback(() => request<Conversation['messages'][number]>(`/conversations/${conversationId}/messages`, { method: 'POST', body: JSON.stringify({ content, messageFormat }) }), async () => ({ id: id('agent'), role: 'agent' as const, content, messageFormat, createdAt: new Date().toISOString() })),
  },
  leads: {
    list: () => withFallback(() => request<PageResult<Lead>>('/leads'), async () => { await pause(); const items = demoLeadList(); return { items, total: items.length, page: 1, pageSize: 50 }; }),
    updateStatus: (leadId: string, status: string) => withFallback(() => request<Lead>(`/leads/${leadId}`, { method: 'PATCH', body: JSON.stringify({ status }) }), async () => {
      await pause(); const items = demoLeadList(); const lead = items.find((item) => item.id === leadId); if (!lead) throw new ApiError('Lead not found', 404);
      lead.status = status; lead.updatedAt = new Date().toISOString(); writeStorage(LEADS_KEY, items); return lead;
    }),
  },
  analytics: { summary: (days?: 7 | 30) => withFallback(() => request<AnalyticsSummary>(`/analytics/summary${days ? `?days=${days}` : ''}`), async () => { await pause(); return clone(demoAnalytics); }) },
  integrations: {
    list: () => withFallback(() => request<Integration[]>('/integrations'), async () => { await pause(); return demoIntegrationList(); }),
    setConnected: (integrationId: string, connected: boolean) => withFallback(() => request<Integration>(`/integrations/${integrationId}`, { method: 'PATCH', body: JSON.stringify({ connected }) }), async () => {
      await pause(); const items = demoIntegrationList(); const index = items.findIndex((item) => item.id === integrationId); if (index < 0) throw new ApiError('Integration not found', 404);
      const result = { ...items[index]!, connected }; items[index] = result; writeStorage(INTEGRATIONS_KEY, items); return result;
    }),
    whatsapp: {
      accounts: () => request<import('@/types').WhatsAppAccount[]>('/integrations/whatsapp-accounts'),
      updateAccount: (accountId: string, input: { name: string; appId: string; appSecret: string; accessToken: string; wabaId: string; verifyToken: string }) => request<import('@/types').WhatsAppAccount>(`/integrations/whatsapp-accounts/${accountId}`, { method: 'PUT', body: JSON.stringify(input) }),
      addAccount: (input: { name: string; appId: string; appSecret: string; accessToken: string; wabaId: string; verifyToken: string }) => request<import('@/types').WhatsAppAccount>('/integrations/whatsapp-accounts', { method: 'POST', body: JSON.stringify(input) }),
      accountNumbers: (accountId: string) => request<{ id: string; displayPhoneNumber: string; verifiedName: string }[]>(`/integrations/whatsapp-accounts/${accountId}/numbers`),
      addNumber: (accountId: string, phoneNumberId: string, pin: string) => request<WhatsAppConnection>(`/integrations/whatsapp-accounts/${accountId}/numbers`, { method: 'POST', body: JSON.stringify({ phoneNumberId, pin }) }),
      connectWebhook: (accountId: string) => request<import('@/types').WhatsAppAccount>(`/integrations/whatsapp-accounts/${accountId}/webhook`, { method: 'POST' }),
      assignNumber: (connectionId: string, agentId: string | null) => request<WhatsAppConnection>(`/integrations/whatsapp-accounts/numbers/${connectionId}/assignment`, { method: 'PUT', body: JSON.stringify({ agentId }) }),
      templates: (agentId: string) => request<{ name: string; language: string; fields: { component: string; name: string }[]; preview: string; unsupportedReason: string | null }[]>(`/integrations/whatsapp/${agentId}/templates`),
      sendTemplate: (conversationId: string, template: { name: string; language: string; parameters: string[]; consentConfirmed: true }) => request<Conversation['messages'][number]>(`/conversations/${conversationId}/messages`, { method: 'POST', body: JSON.stringify({ content: template.name, whatsappTemplate: template }) }),
      activity: (agentId: string) => request<{ lastError: string | null; outbound?: { id: string; status: string; at: string; error: string | null }[]; inbound: { id: string; status: string; messageType: string; receivedAt: string; conversationId: string | null; error: string | null }[]; deliveries: { id: string; status: string; at: string; errorCode: string | null }[] }>(`/integrations/whatsapp/${agentId}/activity`),
      check: (agentId: string) => request<WhatsAppConnection>(`/integrations/whatsapp/${agentId}/check`, { method: 'POST' }),
      bootstrap: () => request<WhatsAppBootstrap>('/integrations/whatsapp/bootstrap'),
      status: () => request<WhatsAppStatus>('/integrations/whatsapp/status'),
      complete: (input: CompleteWhatsAppSignupInput) => request<WhatsAppConnection>('/integrations/whatsapp/complete', {
        method: 'POST', body: JSON.stringify(input),
      }),
      disconnect: (agentId: string) => request<void>(`/integrations/whatsapp/${agentId}`, { method: 'DELETE' }),
    },
  },
  widget: {
    bootstrap: (publicId: string) => withFallback(async () => agentFromWidgetBootstrap(await request<WidgetBootstrap>(`/widget/${publicId}/bootstrap`, {
      skipAuth: true,
      skipRefresh: true,
    })), async () => {
      await pause(120);
      const found = demoAgentList().find((item) => item.publicId === publicId || item.id === publicId);
      if (!found) throw new ApiError('Published agent not found', 404);
      return found;
    }),
    hostedBootstrap: (publicId: string) => withFallback(async () => agentFromWidgetBootstrap(await request<WidgetBootstrap>(`/widget/${publicId}/hosted/bootstrap`, {
      skipAuth: true,
      skipRefresh: true,
    })), async () => {
      await pause(120);
      const found = demoAgentList().find((item) => item.publicId === publicId || item.id === publicId);
      if (!found) throw new ApiError('Published agent not found', 404);
      return found;
    }),
    createSession: (publicId: string) => withFallback(() => request<WidgetSession>(`/widget/${publicId}/sessions`, {
      method: 'POST', body: JSON.stringify({ pageUrl: window.location.href }), skipAuth: true, skipRefresh: true,
    }), async () => ({ conversationId: id('conv'), conversationPublicId: id('public-conv'), sessionToken: id('widget-token'), expiresAt: new Date(Date.now() + 3_600_000).toISOString() })),
    createHostedSession: (publicId: string) => withFallback(() => request<WidgetSession>(`/widget/${publicId}/hosted/sessions`, {
      method: 'POST', body: JSON.stringify({ pageUrl: window.location.href }), skipAuth: true, skipRefresh: true,
    }), async () => ({ conversationId: id('conv'), conversationPublicId: id('public-conv'), sessionToken: id('widget-token'), expiresAt: new Date(Date.now() + 3_600_000).toISOString() })),
    async *streamChat(input: { conversationId: string; sessionToken: string; message: string; language?: string }, signal?: AbortSignal): AsyncGenerator<ChatStreamEvent> {
      try {
        const response = await fetch(`${API_URL}/widget/sessions/${input.conversationId}/messages`, {
          method: 'POST', signal,
          headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream', Authorization: `Bearer ${input.sessionToken}` },
          body: JSON.stringify({ message: input.message, idempotencyKey: crypto.randomUUID?.() ?? id('turn') }),
        });
        yield* parseChatEvents(response);
        return;
      } catch (error) {
        if (signal?.aborted) return;
        if (!DEMO_MODE) { yield { type: 'error', message: error instanceof Error ? error.message : 'Chat unavailable' }; return; }
      }
      yield* demoChatEvents(input.message, input.conversationId, signal, input.language);
    },
  },
  async *streamChat(input: ChatStreamRequest & { language?: string }, signal?: AbortSignal): AsyncGenerator<ChatStreamEvent> {
    const { language, ...requestInput } = input;
    try {
      const active = session();
      const workspaceId = activeWorkspaceId();
      const response = await fetch(`${API_URL}/chat/stream`, { method: 'POST', signal, headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream', ...(active ? { Authorization: `Bearer ${active.accessToken}` } : {}), ...(workspaceId ? { 'X-Workspace-ID': workspaceId } : {}) }, body: JSON.stringify(requestInput) });
      yield* parseChatEvents(response);
      return;
    } catch (error) {
      if (signal?.aborted) return;
      if (!DEMO_MODE) { yield { type: 'error', message: error instanceof Error ? error.message : 'Chat unavailable' }; return; }
    }
    const selectedLanguage = language ?? demoAgentList().find((agent) => agent.id === input.agentId)?.language ?? 'English';
    yield* demoChatEvents(input.message, input.conversationId, signal, selectedLanguage);
  },
};

function templateInstructions(template?: string): string {
  if (template === 'support') return 'Answer customer questions using trusted knowledge. Be clear, helpful, and escalate when information is missing.';
  if (template === 'lead') return 'Qualify each lead with one useful question at a time, understand their needs, and recommend the appropriate next step.';
  return 'Help visitors with accurate, concise answers. Use trusted knowledge first and clearly say when information is unavailable.';
}

function demoDisplayQuestion(question: string, language = 'English'): string {
  const trimmed = question.trim();
  if (!trimmed || language === 'English') return trimmed;

  const targetScript: Partial<Record<string, RegExp>> = {
    Hindi: /[\u0900-\u097f]/,
    Arabic: /[\u0600-\u06ff]/,
  };
  if (targetScript[language]?.test(trimmed)) return trimmed;

  const normalized = trimmed.toLowerCase().replace(/[^a-z0-9\s]/g, '').replace(/\s+/g, ' ').trim();
  const phrases: Record<string, Record<string, string>> = {
    Hindi: {
      hi: 'नमस्ते', hii: 'नमस्ते', hello: 'नमस्ते',
      'what services do you offer': 'आप कौन-सी सेवाएँ देते हैं?',
      'how can i contact support': 'मैं सहायता से कैसे संपर्क करूँ?',
      'tell me about your plans': 'अपनी योजनाओं के बारे में बताएँ।',
      'what is cse': 'सीएसई क्या है?',
      'how are you': 'आप कैसे हैं?',
    },
    Spanish: {
      hi: 'Hola', hii: 'Hola', hello: 'Hola',
      'what services do you offer': '¿Qué servicios ofrecen?',
      'how can i contact support': '¿Cómo puedo contactar con soporte?',
      'tell me about your plans': 'Cuéntame sobre sus planes.',
      'what is cse': '¿Qué es CSE?', 'how are you': '¿Cómo estás?',
    },
    French: {
      hi: 'Bonjour', hii: 'Bonjour', hello: 'Bonjour',
      'what services do you offer': 'Quels services proposez-vous ?',
      'how can i contact support': 'Comment puis-je contacter le support ?',
      'tell me about your plans': 'Parlez-moi de vos offres.',
      'what is cse': "Qu'est-ce que CSE ?", 'how are you': 'Comment allez-vous ?',
    },
    German: {
      hi: 'Hallo', hii: 'Hallo', hello: 'Hallo',
      'what services do you offer': 'Welche Dienstleistungen bieten Sie an?',
      'how can i contact support': 'Wie kann ich den Support kontaktieren?',
      'tell me about your plans': 'Erzählen Sie mir von Ihren Tarifen.',
      'what is cse': 'Was ist CSE?', 'how are you': 'Wie geht es Ihnen?',
    },
    Arabic: {
      hi: 'مرحبًا', hii: 'مرحبًا', hello: 'مرحبًا',
      'what services do you offer': 'ما الخدمات التي تقدمونها؟',
      'how can i contact support': 'كيف يمكنني التواصل مع الدعم؟',
      'tell me about your plans': 'أخبرني عن خططكم.',
      'what is cse': 'ما هو CSE؟', 'how are you': 'كيف حالك؟',
    },
  };

  const exact = phrases[language]?.[normalized];
  if (exact) return exact;

  const subject = normalized.match(/^what is (.+)$/)?.[1];
  if (subject) {
    const questionTemplates: Record<string, (value: string) => string> = {
      Hindi: (value) => `${value} क्या है?`,
      Spanish: (value) => `¿Qué es ${value}?`,
      French: (value) => `Qu'est-ce que ${value} ?`,
      German: (value) => `Was ist ${value}?`,
      Arabic: (value) => `ما هو ${value}؟`,
    };
    return questionTemplates[language]?.(subject) ?? trimmed;
  }

  const topic = normalized.match(/^tell me about (.+)$/)?.[1];
  if (topic) {
    const topicTemplates: Record<string, (value: string) => string> = {
      Hindi: (value) => `${value} के बारे में बताएँ।`,
      Spanish: (value) => `Cuéntame sobre ${value}.`,
      French: (value) => `Parlez-moi de ${value}.`,
      German: (value) => `Erzählen Sie mir von ${value}.`,
      Arabic: (value) => `أخبرني عن ${value}.`,
    };
    return topicTemplates[language]?.(topic) ?? trimmed;
  }

  return trimmed;
}

function demoAnswer(question: string, language = 'English'): string {
  const value = question.toLowerCase();
  const kind = value.includes('price') || value.includes('plan') ? 'plans' : value.includes('contact') || value.includes('support') ? 'support' : value.includes('service') || value.includes('offer') ? 'services' : 'default';
  const answers: Record<string, Record<string, string>> = {
    English: { plans: 'Our plans scale with your team and conversation volume. Tell me your team size and I can help you choose.', support: 'You can contact the support team from the Help menu or ask me to escalate this conversation.', services: 'Northstar helps teams create accurate AI agents, train them on trusted sources, review conversations, and deploy them across connected channels.', default: 'I found relevant guidance in the connected knowledge base. Check that the agent knowledge is current, then test the answer in the live preview. Would you like the steps?' },
    Hindi: { plans: 'हमारी योजनाएँ आपकी टीम और बातचीत की मात्रा के अनुसार बढ़ती हैं। अपनी टीम का आकार बताएं, मैं सही योजना चुनने में मदद करूँगा।', support: 'आप सहायता मेनू से सपोर्ट टीम से संपर्क कर सकते हैं या मुझसे इस बातचीत को आगे भेजने के लिए कह सकते हैं।', services: 'नॉर्थस्टार टीमों को सटीक एआई एजेंट बनाने, विश्वसनीय स्रोतों से प्रशिक्षित करने, बातचीत की समीक्षा करने और जुड़े चैनलों पर तैनात करने में मदद करता है।', default: 'मुझे जुड़े ज्ञान आधार में उपयोगी जानकारी मिली है। एजेंट का ज्ञान अद्यतन है या नहीं जाँचें, फिर लाइव पूर्वावलोकन में जवाब का परीक्षण करें। क्या आप चरण जानना चाहेंगे?' },
    Spanish: { plans: 'Nuestros planes crecen con tu equipo y el volumen de conversaciones. Dime el tamaño de tu equipo y te ayudaré a elegir.', support: 'Puedes contactar al equipo de soporte desde el menú Ayuda o pedirme que derive esta conversación.', services: 'Northstar ayuda a crear agentes de IA precisos, entrenarlos con fuentes fiables, revisar conversaciones y desplegarlos en canales conectados.', default: 'Encontré información útil en la base de conocimiento conectada. Comprueba que el conocimiento esté actualizado y prueba la respuesta en la vista previa. ¿Quieres ver los pasos?' },
    French: { plans: 'Nos offres évoluent avec votre équipe et votre volume de conversations. Indiquez-moi la taille de votre équipe pour choisir.', support: 'Vous pouvez contacter le support depuis le menu Aide ou me demander de transmettre cette conversation.', services: 'Northstar aide les équipes à créer des agents IA précis, à les former avec des sources fiables, à examiner les conversations et à les déployer sur plusieurs canaux.', default: 'J’ai trouvé des informations utiles dans la base de connaissances connectée. Vérifiez qu’elle est à jour, puis testez la réponse dans l’aperçu. Voulez-vous les étapes ?' },
    German: { plans: 'Unsere Tarife wachsen mit Ihrem Team und Gesprächsvolumen. Nennen Sie mir Ihre Teamgröße, dann helfe ich bei der Auswahl.', support: 'Sie erreichen den Support über das Hilfe-Menü oder können mich bitten, dieses Gespräch weiterzuleiten.', services: 'Northstar hilft Teams, präzise KI-Agenten zu erstellen, mit verlässlichen Quellen zu trainieren, Gespräche zu prüfen und über verbundene Kanäle bereitzustellen.', default: 'Ich habe passende Informationen in der verbundenen Wissensbasis gefunden. Prüfen Sie deren Aktualität und testen Sie die Antwort in der Live-Vorschau. Möchten Sie die Schritte sehen?' },
    Arabic: { plans: 'تتوسع خططنا حسب حجم فريقك وعدد المحادثات. أخبرني بحجم فريقك وسأساعدك في الاختيار.', support: 'يمكنك التواصل مع فريق الدعم من قائمة المساعدة أو أن تطلب مني تصعيد هذه المحادثة.', services: 'يساعد نورث ستار الفرق على إنشاء وكلاء ذكاء اصطناعي دقيقين وتدريبهم على مصادر موثوقة ومراجعة المحادثات ونشرهم عبر القنوات المتصلة.', default: 'وجدت معلومات مفيدة في قاعدة المعرفة المتصلة. تحقق من تحديث معرفة الوكيل ثم اختبر الإجابة في المعاينة المباشرة. هل تريد الخطوات؟' },
  };
  const selected = answers[language] ?? answers.English!;
  return selected[kind] ?? selected.default!;
}

export const apiConfig = { baseUrl: API_URL, demoMode: DEMO_MODE } as const;
