import type { Session } from '@/types';
import { activeWorkspaceId } from '@/lib/workspace-api';
import type { CRMProviderId } from '@/lib/lead-crm-api';

const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? '/api/v1';
const SESSION_KEY = 'northstar.session';

export type CRMOneClickMode = 'oauth' | 'api_key' | 'rest';

export interface CRMOneClickProvider {
  id: CRMProviderId;
  name: string;
  mode: CRMOneClickMode;
  configured: boolean;
  requiredInputs: string[];
  supportsSandbox: boolean;
  supportsReadBack: boolean;
  oauthRedirectUri?: string;
}

export interface CRMReadiness {
  connectionId: string;
  provider: CRMProviderId;
  status: string;
  ready: boolean;
  liveCertified: boolean;
  blockers: string[];
  schemaHash?: string | null;
  mappingVersion?: number | null;
  routeId?: string | null;
  autoSyncNewLeads: boolean;
  autoSyncUpdates: boolean;
  eventPipelineReady: boolean;
  verifiedDeliveryId?: string | null;
  externalRecordId?: string | null;
  certifiedAt?: string | null;
}

export interface CRMOneClickStartRequest {
  name?: string;
  environment?: 'production' | 'sandbox';
  region?: string;
  resource_url?: string;
  azure_tenant_id?: string;
  client_id?: string;
  client_secret?: string;
}

export interface CRMDirectActivateRequest {
  name?: string;
  base_url: string;
  api_key?: string;
  token?: string;
  auth_type?: 'NONE' | 'BEARER' | 'API_KEY_HEADER';
  api_key_header?: string;
  health_path?: string;
  upsert_path?: string;
  get_path?: string;
  external_id_path?: string;
  read_back_id_path?: string;
}

export interface CRMAcceptanceTestResult {
  queued: boolean;
  leadId: string;
  deliveryId: string;
  connectionId: string;
  provider: CRMProviderId;
  status: string;
  message: string;
}

export interface CRMAcceptanceTestStatus {
  connectionId: string;
  deliveryId: string;
  leadId: string;
  provider: CRMProviderId;
  status: string;
  acknowledged: boolean;
  acknowledgedAt?: string | null;
  verificationStatus: string;
  verified: boolean;
  verifiedAt?: string | null;
  externalRecordId?: string | null;
  providerRequestId?: string | null;
  nextRetryAt?: string | null;
  nextVerificationAt?: string | null;
  errorCode?: string | null;
  errorMessage?: string | null;
}

export interface CRMOAuthPopupMessage {
  type: 'northstar:crm-oauth';
  success: boolean;
  connectionId?: string;
  provider?: CRMProviderId;
  status?: string;
  message?: string;
  readiness?: CRMReadiness;
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
  const session = currentSession();
  const workspaceId = activeWorkspaceId();
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    credentials: 'include',
    headers: {
      Accept: 'application/json',
      ...(init.body ? { 'Content-Type': 'application/json' } : {}),
      ...(session ? { Authorization: `Bearer ${session.accessToken}` } : {}),
      ...(workspaceId ? { 'X-Workspace-ID': workspaceId } : {}),
      ...init.headers,
    },
  });
  if (!response.ok) {
    const contentType = response.headers.get('content-type') ?? '';
    if (contentType.includes('application/json')) {
      const body = await response.json().catch(() => null) as { detail?: unknown; error?: { message?: string } } | null;
      if (body?.error?.message) throw new Error(body.error.message);
      const detail = body?.detail;
      if (typeof detail === 'string') throw new Error(detail);
      if (detail && typeof detail === 'object' && 'message' in detail) {
        throw new Error(String((detail as { message: unknown }).message));
      }
      throw new Error(`Connection request failed (${response.status}). Check the required fields and try again.`);
    }
    throw new Error(await response.text().catch(() => '') || `Request failed (${response.status})`);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const crmOneClickApi = {
  callbackOrigin(): string {
    return new URL(API_URL, window.location.origin).origin;
  },
  providers: () => call<CRMOneClickProvider[]>('/crm/one-click/providers'),
  startOAuth: (provider: CRMProviderId, value: CRMOneClickStartRequest = {}) =>
    call<{ authorizationUrl: string; connectionId: string; provider: CRMProviderId; workspaceId: string; responseMode: 'popup' }>(
      `/crm/one-click/${provider}/start`,
      { method: 'POST', body: JSON.stringify(value) },
    ),
  activateDirect: (provider: CRMProviderId, value: CRMDirectActivateRequest) =>
    call<CRMReadiness & { schemaFieldCount: number }>(`/crm/one-click/${provider}/activate`, {
      method: 'POST',
      body: JSON.stringify(value),
    }),
  readiness: (connectionId: string) =>
    call<CRMReadiness>(`/crm/connections/${encodeURIComponent(connectionId)}/readiness`),
  provision: (connectionId: string) =>
    call<CRMReadiness & { schemaFieldCount: number }>(
      `/crm/connections/${encodeURIComponent(connectionId)}/provision`,
      { method: 'POST' },
    ),
  acceptanceTest: (connectionId: string) =>
    call<CRMAcceptanceTestResult>(
      `/crm/connections/${encodeURIComponent(connectionId)}/acceptance-test`,
      { method: 'POST', body: JSON.stringify({}) },
    ),
  acceptanceStatus: (connectionId: string, deliveryId: string) =>
    call<CRMAcceptanceTestStatus>(
      `/crm/connections/${encodeURIComponent(connectionId)}/acceptance-test/${encodeURIComponent(deliveryId)}`,
    ),
};
