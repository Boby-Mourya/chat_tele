import type { Lead, PageResult, Session } from '@/types';
import { activeWorkspaceId } from '@/lib/workspace-api';

const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? '/api/v1';
const SESSION_KEY = 'northstar.session';

export interface TelegramBotInfo {
  managed: boolean;
  botId: string;
  botName: string;
  botUsername: string;
  studentUrl: string;
}
export interface TelegramProvisioningStatus {
  sessionId: string;
  status: string;
  connectionId: string | null;
  telegramUrl?: string;
  error?: string | null;
  bot?: TelegramBotInfo | null;
}

export type CRMProviderId = 'zoho' | 'salesforce' | 'hubspot' | 'dynamics365' | 'pipedrive' | 'freshsales' | 'generic_rest' | 'generic_webhook';
export type CRMHealthState = 'healthy' | 'degraded' | 'unhealthy' | 'auth_required' | 'rate_limited' | 'configuration_error' | 'unknown' | 'draft' | 'connecting' | 'disabled';

export interface CRMProviderInfo {
  id: CRMProviderId;
  name: string;
  oauth: boolean;
  schemaDiscovery: boolean;
  upsert: boolean;
  readBack: boolean;
  inboundWebhooks: boolean;
  webhookManagement: boolean;
  runtimeRegistered: boolean;
}

export interface CRMConnectionView {
  id: string;
  public_id: string;
  provider: CRMProviderId;
  name: string;
  environment: string;
  region?: string | null;
  status: CRMHealthState;
  configuration: Record<string, unknown>;
  capabilities: Record<string, unknown>;
  last_authenticated_at?: string | null;
  last_health_at?: string | null;
  last_success_at?: string | null;
  last_failure_at?: string | null;
  last_error?: string | null;
  created_at: string;
  updated_at: string;
}

export interface CRMWorkspaceSettings {
  connection_id: string;
  auto_sync_new_leads: boolean;
  auto_sync_updates: boolean;
  updated_at: string;
}

export interface CRMFieldSchemaView {
  connectionId: string;
  objectName: string;
  schemaHash?: string | null;
  fields: Array<{
    apiName: string;
    label: string;
    dataType: string;
    required: boolean;
    nullable: boolean;
    readOnly: boolean;
    unique: boolean;
    custom: boolean;
    maxLength?: number | null;
    picklistValues: string[];
  }>;
}

export interface CRMMappingView {
  connection_id: string;
  object_name: string;
  version: number;
  status: string;
  mapping: Record<string, unknown>;
  validation: Record<string, unknown>;
  schema_hash?: string | null;
}

export interface CRMRouteView {
  id: string;
  name: string;
  enabled: boolean;
  priority: number;
  version: number;
  conditions: Record<string, unknown>;
  connection_ids: string[];
  created_at: string;
  updated_at: string;
}

export interface CRMDeliveryView {
  id: string;
  lead_id: string;
  connection_id: string;
  provider: CRMProviderId;
  operation: string;
  status: string;
  verification_status?: string;
  verification_attempt_count?: number;
  next_verification_at?: string | null;
  verification_error_code?: string | null;
  verification_error_message?: string | null;
  verification_evidence?: Record<string, unknown>;
  external_record_id?: string | null;
  attempt_count: number;
  queued_at?: string | null;
  sent_at?: string | null;
  acknowledged_at?: string | null;
  verified_at?: string | null;
  next_retry_at?: string | null;
  last_error_code?: string | null;
  last_error_message?: string | null;
  provider_http_status?: number | null;
  provider_code?: string | null;
  provider_request_id?: string | null;
  created_at: string;
}

export interface CRMDeliveryAttemptView {
  id: string;
  delivery_id: string;
  attempt_number: number;
  started_at: string;
  finished_at?: string | null;
  http_status?: number | null;
  latency_ms?: number | null;
  result_status?: string | null;
  normalized_error_code?: string | null;
  provider_error_code?: string | null;
  provider_request_id?: string | null;
}

export interface CRMHealthSnapshotView {
  id: string;
  connection_id: string;
  status: string;
  checks: Record<string, string>;
  latency_ms?: number | null;
  checked_at: string;
}

export interface LeadActivityView {
  id: string;
  event_type: string;
  actor_type: string;
  actor_id?: string | null;
  correlation_id?: string | null;
  details: Record<string, unknown>;
  occurred_at: string;
}

export interface CRMConnectionHealth {
  connectionId: string;
  provider: CRMProviderId;
  status: CRMHealthState;
  checks: Record<string, string>;
  latencyMs?: number | null;
  details: Record<string, unknown>;
  queue: { pending: number; retrying: number; deadLetter: number };
  lastSuccessAt?: string | null;
  lastFailureAt?: string | null;
}

export interface ChannelProviderInfo { id: string; name: string; runtimeRegistered: boolean }
export interface ChannelConnectionView {
  id: string;
  public_id: string;
  workspace_id: string;
  agent_id?: string | null;
  provider: string;
  name: string;
  status: string;
  configuration: Record<string, unknown>;
  webhook_path?: string;
  last_health_at?: string | null;
  last_event_at?: string | null;
  last_failure_at?: string | null;
  last_error?: string | null;
  created_at: string;
  updated_at: string;
}

function currentSession(): Session | null {
  try {
    const raw = localStorage.getItem(SESSION_KEY);
    return raw ? JSON.parse(raw) as Session : null;
  } catch {
    return null;
  }
}

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const active = currentSession();
  const workspaceId = activeWorkspaceId();
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    credentials: 'include',
    headers: {
      Accept: 'application/json',
      ...(init.body ? { 'Content-Type': 'application/json' } : {}),
      ...(active ? { Authorization: `Bearer ${active.accessToken}` } : {}),
      ...(workspaceId ? { 'X-Workspace-ID': workspaceId } : {}),
      ...init.headers,
    },
  });
  if (!response.ok) {
    const body = await response.text().catch(() => '');
    let message = `Request failed (${response.status})`;
    try {
      const value = JSON.parse(body) as { detail?: unknown; error?: { message?: string } };
      if (value.error?.message) message = value.error.message;
      else if (typeof value.detail === 'string') message = value.detail;
    } catch { if (body && !body.includes('<')) message = body; }
    throw new Error(message);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const leadCrmApi = {
  connectionEntitlements: () => call<{ plan: string; features: { crm: boolean; allowedChannels: string[] } }>('/billing/entitlements'),
  leads: (filters: { page?: number; pageSize?: number; search?: string; status?: string; agentId?: string; channel?: string; crmStatus?: string } = {}) => {
    const params = new URLSearchParams();
    if (filters.page) params.set('page', String(filters.page));
    if (filters.pageSize) params.set('page_size', String(filters.pageSize));
    if (filters.search?.trim()) params.set('search', filters.search.trim());
    if (filters.status && filters.status !== 'all') params.set('status', filters.status);
    if (filters.agentId && filters.agentId !== 'all') params.set('agent_id', filters.agentId);
    if (filters.channel && filters.channel !== 'all') params.set('channel', filters.channel);
    if (filters.crmStatus && filters.crmStatus !== 'all') params.set('crm_status', filters.crmStatus);
    const query = params.toString();
    return call<PageResult<Lead>>(`/leads${query ? `?${query}` : ''}`);
  },
  providers: () => call<CRMProviderInfo[]>('/crm/providers'),
  connections: () => call<CRMConnectionView[]>('/crm/connections'),
  createConnection: (value: { provider: CRMProviderId; name: string; environment?: string; region?: string; configuration?: Record<string, unknown>; credentials?: Record<string, unknown> }) =>
    call<CRMConnectionView>('/crm/connections', { method: 'POST', body: JSON.stringify(value) }),
  workspaceSettings: (id: string) => call<CRMWorkspaceSettings>(`/crm/connections/${id}/workspace-settings`),
  updateWorkspaceSettings: (id: string, value: Partial<Pick<CRMWorkspaceSettings, 'auto_sync_new_leads' | 'auto_sync_updates'>>) =>
    call<CRMWorkspaceSettings>(`/crm/connections/${id}/workspace-settings`, { method: 'PATCH', body: JSON.stringify(value) }),
  testConnection: (id: string) => call<CRMConnectionHealth>(`/crm/connections/${id}/test`, { method: 'POST' }),
  runHealthCheck: (id: string) => call<CRMHealthSnapshotView>(`/crm/connections/${id}/health-check`, { method: 'POST' }),
  healthHistory: (id: string, limit = 50) => call<CRMHealthSnapshotView[]>(`/crm/connections/${id}/health-history?limit=${limit}`),
  startOAuth: (id: string) => call<{ authorizationUrl: string; expiresIn: number; workspaceId?: string }>(`/crm/connections/${id}/oauth/start`, { method: 'POST' }),
  reconnect: (id: string) => call<{ authorizationUrl: string; expiresIn: number; workspaceId?: string }>(`/crm/connections/${id}/reconnect`, { method: 'POST' }),
  disableConnection: (id: string) => call<void>(`/crm/connections/${id}`, { method: 'DELETE' }),
  health: (id: string) => call<CRMConnectionHealth>(`/crm/connections/${id}/health`),
  schema: (id: string) => call<CRMFieldSchemaView>(`/crm/connections/${id}/schema`),
  refreshSchema: (id: string) => call<CRMFieldSchemaView>(`/crm/connections/${id}/schema/refresh`, { method: 'POST' }),
  mappings: (id: string) => call<CRMMappingView[]>(`/crm/connections/${id}/mappings`),
  putMapping: (id: string, value: { object_name?: string; mapping: Record<string, unknown> }) =>
    call<CRMMappingView>(`/crm/connections/${id}/mappings`, { method: 'PUT', body: JSON.stringify(value) }),
  validateMappings: (id: string) => call<Record<string, unknown>>(`/crm/connections/${id}/mappings/validate`, { method: 'POST' }),
  routes: () => call<CRMRouteView[]>('/crm/routes'),
  createRoute: (value: { name: string; enabled?: boolean; priority?: number; conditions?: Record<string, unknown>; connection_ids: string[] }) =>
    call<CRMRouteView>('/crm/routes', { method: 'POST', body: JSON.stringify(value) }),
  updateRoute: (id: string, value: { name?: string; enabled?: boolean; priority?: number; conditions?: Record<string, unknown>; connection_ids?: string[] }) =>
    call<CRMRouteView>(`/crm/routes/${id}`, { method: 'PATCH', body: JSON.stringify(value) }),
  deleteRoute: (id: string) => call<void>(`/crm/routes/${id}`, { method: 'DELETE' }),
  deliveriesForLead: (leadId: string) => call<CRMDeliveryView[]>(`/leads/${leadId}/deliveries`),
  deliveryAttempts: (deliveryId: string) => call<CRMDeliveryAttemptView[]>(`/crm/deliveries/${deliveryId}/attempts`),
  activityForLead: (leadId: string) => call<LeadActivityView[]>(`/leads/${leadId}/activity`),
  syncLead: (leadId: string, reason = 'manual') => call(`/leads/${leadId}/sync`, { method: 'POST', body: JSON.stringify({ reason }) }),
  qualifyLead: (leadId: string, score: number, reason: string) => call(`/leads/${leadId}/qualify`, { method: 'POST', body: JSON.stringify({ score, reason }) }),
  retryDelivery: (id: string) => call<CRMDeliveryView>(`/crm/deliveries/${id}/retry`, { method: 'POST' }),
  cancelDelivery: (id: string) => call<CRMDeliveryView>(`/crm/deliveries/${id}/cancel`, { method: 'POST' }),
  channelProviders: () => call<ChannelProviderInfo[]>('/channels/providers'),
  channelConnections: () => call<ChannelConnectionView[]>('/channels/connections'),
  startTelegramConnection: (agentId: string, account?: { accountId?: string; connectionId?: string }) => call<TelegramProvisioningStatus>('/channels/telegram/connect/start', { method: 'POST', body: JSON.stringify({ agentId, ...account }) }),
  getTelegramProvisioningStatus: (id: string) => call<TelegramProvisioningStatus>(`/channels/telegram/provisioning/${id}`),
  disconnectTelegramConnection: (id: string) => call<void>(`/channels/connections/${id}`, { method: 'DELETE' }),
  createChannelConnection: (value: { provider: string; name: string; agentId?: string; configuration?: Record<string, unknown>; credentials?: Record<string, unknown> }) =>
    call<ChannelConnectionView>('/channels/connections', { method: 'POST', body: JSON.stringify(value) }),
  testChannelConnection: (id: string) => call<Record<string, string>>(`/channels/connections/${id}/test`, { method: 'POST' }),
  updateChannelConnection: (id: string, value: { provider: string; name: string; agentId?: string; configuration?: Record<string, unknown>; credentials?: Record<string, unknown> }) =>
    call<ChannelConnectionView>(`/channels/connections/${id}`, { method: 'PATCH', body: JSON.stringify(value) }),
  disableChannelConnection: (id: string) => call<void>(`/channels/connections/${id}`, { method: 'DELETE' }),
};
