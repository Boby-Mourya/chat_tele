import type { Session } from '@/types';
import { activeWorkspaceId } from '@/lib/workspace-api';

const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? '/api/v1';
const SESSION_KEY = 'northstar.session';

export interface ChannelOperationalConnectionHealth {
  connection_id: string;
  name: string;
  provider: string;
  status: string;
  last_health_at?: string | null;
  last_event_at?: string | null;
  last_failure_at?: string | null;
  last_error?: string | null;
  pending_deliveries: number;
  retrying_deliveries: number;
  failed_deliveries: number;
  pending_webhook_events: number;
  failed_webhook_events: number;
  rejected_webhook_events: number;
  stale_webhook_events: number;
}

export interface ChannelOperationalHealth {
  overall_status: 'empty' | 'healthy' | 'active' | 'attention';
  connection_count: number;
  healthy_connections: number;
  attention_connections: number;
  pending_deliveries: number;
  retrying_deliveries: number;
  failed_deliveries: number;
  pending_webhook_events: number;
  failed_webhook_events: number;
  rejected_webhook_events: number;
  stale_webhook_events: number;
  connections: ChannelOperationalConnectionHealth[];
}

function currentSession(): Session | null {
  try {
    const raw = localStorage.getItem(SESSION_KEY);
    return raw ? JSON.parse(raw) as Session : null;
  } catch {
    return null;
  }
}

export const channelOperationsApi = {
  async health(): Promise<ChannelOperationalHealth> {
    const active = currentSession();
    const workspaceId = activeWorkspaceId();
    const response = await fetch(`${API_URL}/channels/operations/health`, {
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
    return response.json() as Promise<ChannelOperationalHealth>;
  },
};
