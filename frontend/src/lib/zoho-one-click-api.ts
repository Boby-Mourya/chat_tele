import { readStorage } from '@/lib/storage';
import { activeWorkspaceId } from '@/lib/workspace-api';

const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? '/api/v1';
const SESSION_KEY = 'northstar.session';

export interface ZohoLiveCertification {
  status: 'verified' | 'failed' | 'skipped' | string;
  externalRecordId?: string | null;
  providerRequestId?: string | null;
  providerCode?: string | null;
  action?: string | null;
  verifiedFields?: string[];
  verifiedAt?: string | null;
  certificationEmail?: string | null;
  reason?: string | null;
}

export interface ZohoOneClickStatus {
  platformConfigured: boolean;
  connected: boolean;
  status: string;
  connectionId?: string | null;
  connectionName?: string | null;
  autoSyncNewLeads: boolean;
  autoSyncUpdates: boolean;
  mappingReady: boolean;
  mappingVersion?: number | null;
  routeReady: boolean;
  lastHealthAt?: string | null;
  lastSuccessAt?: string | null;
  lastError?: string | null;
  liveCertification?: ZohoLiveCertification | null;
  missingConfiguration: string[];
}

export interface ZohoOneClickStart {
  authorizationUrl: string;
  expiresIn: number;
  connectionId: string;
  provider: 'zoho';
  workspaceId: string;
  oneClick: true;
  willConfigureMapping: boolean;
  willConfigureRouting: boolean;
  willRunLiveCertification: boolean;
}

export interface ZohoCertificationResult {
  connectionId: string;
  mappingId: string;
  routeId: string;
  liveTest: string;
  externalRecordId?: string | null;
  verifiedFields: string[];
}

function accessToken(): string | undefined {
  return readStorage<{ accessToken?: string } | null>(SESSION_KEY, null)?.accessToken;
}

async function request<T>(path: string, method: 'GET' | 'POST'): Promise<T> {
  const token = accessToken();
  const workspaceId = activeWorkspaceId();
  const response = await fetch(`${API_URL}${path}`, {
    method,
    credentials: 'include',
    headers: {
      Accept: 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(workspaceId ? { 'X-Workspace-ID': workspaceId } : {}),
    },
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as {
      error?: { message?: string };
      detail?: string;
    } | null;
    throw new Error(
      payload?.error?.message
      ?? payload?.detail
      ?? `Zoho integration request failed (${response.status})`,
    );
  }
  return response.json() as Promise<T>;
}

export const zohoOneClickApi = {
  status: () => request<ZohoOneClickStatus>('/crm/zoho/one-click/status', 'GET'),
  start: () => request<ZohoOneClickStart>('/crm/zoho/one-click/start', 'POST'),
  certify: () => request<ZohoCertificationResult>('/crm/zoho/one-click/certify', 'POST'),
};
