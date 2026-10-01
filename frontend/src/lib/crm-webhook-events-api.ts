import type { Session } from '@/types';
import { activeWorkspaceId } from '@/lib/workspace-api';

const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? '/api/v1';
const SESSION_KEY = 'northstar.session';

export interface CRMWebhookEventView {
  id: string;
  connection_id: string;
  provider: string;
  event_type: string;
  verification_status: string;
  processing_status: string;
  correlation_id: string;
  received_at: string;
  processed_at?: string | null;
  last_error?: string | null;
}

function currentSession(): Session | null {
  try {
    const raw = localStorage.getItem(SESSION_KEY);
    return raw ? JSON.parse(raw) as Session : null;
  } catch {
    return null;
  }
}

async function call<T>(path: string): Promise<T> {
  const active = currentSession();
  const workspaceId = activeWorkspaceId();
  const response = await fetch(`${API_URL}${path}`, {
    credentials: 'include',
    headers: {
      Accept: 'application/json',
      ...(active ? { Authorization: `Bearer ${active.accessToken}` } : {}),
      ...(workspaceId ? { 'X-Workspace-ID': workspaceId } : {}),
    },
  });
  if (!response.ok) {
    const body = await response.text().catch(() => '');
    throw new Error(body || `Request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

export const crmWebhookEventsApi = {
  list: (filters: { connectionId?: string; processingStatus?: string; limit?: number } = {}) => {
    const params = new URLSearchParams();
    if (filters.connectionId) params.set('connection_id', filters.connectionId);
    if (filters.processingStatus) params.set('processing_status', filters.processingStatus);
    if (filters.limit) params.set('limit', String(filters.limit));
    const query = params.toString();
    return call<CRMWebhookEventView[]>(`/crm/webhook-events${query ? `?${query}` : ''}`);
  },
};
