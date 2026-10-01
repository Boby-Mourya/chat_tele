import type { Session } from '@/types';
import { activeWorkspaceId } from '@/lib/workspace-api';

const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? '/api/v1';
const SESSION_KEY = 'northstar.session';

export type CRMDeadLetterStatus = 'open' | 'resolved' | 'all';

export interface CRMDeadLetterView {
  id: string;
  delivery_id: string;
  lead_id: string;
  connection_id: string;
  provider: string;
  status: string;
  reason_code?: string | null;
  reason_message?: string | null;
  created_at: string;
  updated_at: string;
  resolved_at?: string | null;
}

export interface CRMDeadLetterReplayView {
  dead_letter_id: string;
  delivery_id: string;
  dead_letter_status: string;
  delivery_status: string;
  replayed_at: string;
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
    throw new Error(body || `Request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

export const crmDeadLetterApi = {
  list: (filters: { status?: CRMDeadLetterStatus; connectionId?: string } = {}) => {
    const params = new URLSearchParams();
    if (filters.status) params.set('status', filters.status);
    if (filters.connectionId) params.set('connection_id', filters.connectionId);
    const query = params.toString();
    return call<CRMDeadLetterView[]>(`/crm/dead-letters${query ? `?${query}` : ''}`);
  },
  replay: (deadLetterId: string) => call<CRMDeadLetterReplayView>(
    `/crm/dead-letters/${deadLetterId}/replay`,
    { method: 'POST' },
  ),
};
