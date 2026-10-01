import { activeWorkspaceId } from '@/lib/workspace-api';
import { readStorage } from '@/lib/storage';
import type { Session } from '@/types';

export type NotificationSeverity = 'info' | 'warning' | 'critical';

export interface NotificationItem {
  id: string;
  workspaceId: string | null;
  category: string;
  severity: NotificationSeverity | string;
  title: string;
  body: string;
  actionUrl: string | null;
  actionLabel: string | null;
  metadata: Record<string, unknown>;
  readAt: string | null;
  createdAt: string;
}

const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? '/api/v1';
const SESSION_KEY = 'northstar.session';

class NotificationRequestError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = 'NotificationRequestError';
  }
}

function session(): Session | null {
  return readStorage<Session | null>(SESSION_KEY, null);
}

function headers(): Record<string, string> {
  const active = session();
  const workspaceId = activeWorkspaceId();
  return {
    Accept: 'application/json',
    ...(active ? { Authorization: `Bearer ${active.accessToken}` } : {}),
    ...(workspaceId ? { 'X-Workspace-ID': workspaceId } : {}),
  };
}

async function errorFor(response: Response): Promise<NotificationRequestError> {
  const payload = await response.json().catch(() => null) as { error?: { message?: string } } | null;
  return new NotificationRequestError(
    payload?.error?.message ?? `Notification request failed (${response.status})`,
    response.status,
  );
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    credentials: 'include',
    ...init,
    headers: { ...headers(), ...init.headers },
  });
  if (!response.ok) throw await errorFor(response);
  return response.json() as Promise<T>;
}

export const notificationsApi = {
  list(limit = 30): Promise<NotificationItem[]> {
    return request<NotificationItem[]>(`/notifications?limit=${limit}`);
  },

  async unreadCount(): Promise<number> {
    const payload = await request<{ count: number }>('/notifications/unread-count');
    return payload.count;
  },

  markRead(notificationId: string): Promise<NotificationItem> {
    return request<NotificationItem>(`/notifications/${encodeURIComponent(notificationId)}/read`, {
      method: 'PATCH',
    });
  },

  async markAllRead(): Promise<number> {
    const payload = await request<{ updated: number }>('/notifications/read-all', { method: 'POST' });
    return payload.updated;
  },
};
