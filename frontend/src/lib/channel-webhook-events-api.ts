import type { Session } from '@/types';
import { activeWorkspaceId } from '@/lib/workspace-api';

const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? '/api/v1';
const SESSION_KEY = 'northstar.session';

export interface ChannelWebhookEventView {
  id: string;
  connection_id: string;
  provider: string;
  event_type: string;
  verification_status: string;
  processing_status: string;
  attempt_count: number;
  error_code?: string | null;
  can_requeue: boolean;
  correlation_id: string;
  received_at: string;
  processed_at?: string | null;
}

export interface ChannelWebhookEventFilters {
  connectionId?: string;
  processingStatus?: string;
  provider?: string;
  limit?: number;
}

function currentSession(): Session | null {
  try {
    const raw = localStorage.getItem(SESSION_KEY);
    return raw ? JSON.parse(raw) as Session : null;
  } catch {
    return null;
  }
}

async function call<T>(path: string, method = 'GET'): Promise<T> {
  const active = currentSession();
  const workspaceId = activeWorkspaceId();
  const response = await fetch(`${API_URL}${path}`, {
    method,
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

export const channelWebhookEventsApi = {
  list: ({ connectionId, processingStatus, provider, limit = 100 }: ChannelWebhookEventFilters = {}) => {
    const params = new URLSearchParams();
    if (connectionId) params.set('connection_id', connectionId);
    if (processingStatus) params.set('processing_status', processingStatus);
    if (provider) params.set('provider', provider);
    params.set('limit', String(limit));
    return call<ChannelWebhookEventView[]>(`/channels/webhook-events?${params.toString()}`);
  },
  requeue: (eventId: string) => call<ChannelWebhookEventView>(
    `/channels/webhook-events/${encodeURIComponent(eventId)}/requeue`,
    'POST',
  ),
};
