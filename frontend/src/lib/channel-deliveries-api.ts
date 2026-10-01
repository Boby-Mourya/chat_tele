import type { Session } from '@/types';
import { activeWorkspaceId } from '@/lib/workspace-api';

const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? '/api/v1';
const SESSION_KEY = 'northstar.session';

export interface ChannelOutboundDeliveryView {
  id: string;
  connection_id?: string | null;
  connection_name?: string | null;
  message_id: string;
  provider: string;
  status: string;
  error_code?: string | null;
  attempt_count: number;
  dispatch_attempts: number;
  dispatched_at?: string | null;
  processed_at?: string | null;
  next_dispatch_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface ChannelDeliveryAttemptView {
  id: string;
  delivery_id: string;
  phase: string;
  attempt_number: number;
  outcome: string;
  error_code?: string | null;
  created_at: string;
}

export interface ChannelDeliveryFilters {
  connectionId?: string;
  status?: string;
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

async function call<T>(path: string, method: 'GET' | 'POST' = 'GET'): Promise<T> {
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

export const channelDeliveriesApi = {
  list: ({ connectionId, status, limit = 100 }: ChannelDeliveryFilters = {}) => {
    const params = new URLSearchParams();
    if (connectionId) params.set('connection_id', connectionId);
    if (status) params.set('status', status);
    params.set('limit', String(limit));
    return call<ChannelOutboundDeliveryView[]>(`/channels/deliveries?${params.toString()}`);
  },
  attempts: (deliveryId: string, limit = 100) =>
    call<ChannelDeliveryAttemptView[]>(
      `/channels/deliveries/${encodeURIComponent(deliveryId)}/attempts?limit=${limit}`,
    ),
  requeue: (deliveryId: string) =>
    call<ChannelOutboundDeliveryView>(`/channels/deliveries/${encodeURIComponent(deliveryId)}/requeue`, 'POST'),
};
