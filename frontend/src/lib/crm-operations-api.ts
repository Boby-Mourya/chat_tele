import type { Session } from '@/types';
import { activeWorkspaceId } from '@/lib/workspace-api';

const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? '/api/v1';
const SESSION_KEY = 'northstar.session';

export interface CRMOperationalConnectionHealth {
  connection_id: string;
  name: string;
  provider: string;
  status: string;
  last_health_at?: string | null;
  last_success_at?: string | null;
  last_failure_at?: string | null;
  last_error?: string | null;
  pending_deliveries: number;
  retrying_deliveries: number;
  failed_deliveries: number;
  open_dead_letters: number;
}

export interface CRMOperationalHealth {
  overall_status: 'empty' | 'healthy' | 'active' | 'attention';
  connection_count: number;
  healthy_connections: number;
  attention_connections: number;
  pending_deliveries: number;
  retrying_deliveries: number;
  failed_deliveries: number;
  open_dead_letters: number;
  connections: CRMOperationalConnectionHealth[];
}

function currentSession(): Session | null {
  try {
    const raw = localStorage.getItem(SESSION_KEY);
    return raw ? JSON.parse(raw) as Session : null;
  } catch {
    return null;
  }
}

export const crmOperationsApi = {
  async health(): Promise<CRMOperationalHealth> {
    const active = currentSession();
    const workspaceId = activeWorkspaceId();
    const response = await fetch(`${API_URL}/crm/operations/health`, {
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
    return response.json() as Promise<CRMOperationalHealth>;
  },
};
