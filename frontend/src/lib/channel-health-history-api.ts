import type { Session } from '@/types';
import { activeWorkspaceId } from '@/lib/workspace-api';

const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? '/api/v1';
const SESSION_KEY = 'northstar.session';

export interface ChannelHealthSnapshotView {
  id: string;
  connection_id: string;
  status: string;
  error_code?: string | null;
  checked_at: string;
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

export const channelHealthHistoryApi = {
  list: (connectionId: string, limit = 50) =>
    call<ChannelHealthSnapshotView[]>(`/channels/connections/${encodeURIComponent(connectionId)}/health-history?limit=${limit}`),
};
