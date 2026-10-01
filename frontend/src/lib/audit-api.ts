import { activeWorkspaceId } from '@/lib/workspace-api';
import { readStorage } from '@/lib/storage';
import type { Session } from '@/types';

export type AuditCategory =
  | 'security'
  | 'workspace'
  | 'access'
  | 'agent'
  | 'conversation'
  | 'education'
  | 'lead'
  | 'crm'
  | 'channel'
  | 'billing'
  | 'api'
  | 'integration'
  | 'system';
export type AuditSeverity = 'info' | 'warning' | 'critical';
export type AuditOutcome = 'success' | 'denied' | 'failure';

export interface AuditEvent {
  id: string;
  tenantId: string;
  workspaceId: string | null;
  actorUserId: string | null;
  action: string;
  entityType: string;
  entityId: string;
  category: AuditCategory | string;
  severity: AuditSeverity | string;
  outcome: AuditOutcome | string;
  before: Record<string, unknown>;
  after: Record<string, unknown>;
  metadata: Record<string, unknown>;
  requestId: string | null;
  ipAddress: string | null;
  userAgent: string | null;
  createdAt: string;
}

export interface AuditFilters {
  category?: AuditCategory | '';
  severity?: AuditSeverity | '';
  outcome?: AuditOutcome | '';
  action?: string;
  entityType?: string;
  search?: string;
  from?: string;
  to?: string;
  limit?: number;
}

const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? '/api/v1';
const SESSION_KEY = 'northstar.session';

class AuditRequestError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = 'AuditRequestError';
  }
}

function session(): Session | null {
  return readStorage<Session | null>(SESSION_KEY, null);
}

function query(filters: AuditFilters): string {
  const params = new URLSearchParams();
  if (filters.category) params.set('category', filters.category);
  if (filters.severity) params.set('severity', filters.severity);
  if (filters.outcome) params.set('outcome', filters.outcome);
  if (filters.action?.trim()) params.set('action', filters.action.trim());
  if (filters.entityType?.trim()) params.set('entity_type', filters.entityType.trim());
  if (filters.search?.trim()) params.set('search', filters.search.trim());
  if (filters.from) params.set('from', filters.from);
  if (filters.to) params.set('to', filters.to);
  if (filters.limit) params.set('limit', String(filters.limit));
  const value = params.toString();
  return value ? `?${value}` : '';
}

function headers(accept = 'application/json'): Record<string, string> {
  const active = session();
  const workspaceId = activeWorkspaceId();
  return {
    Accept: accept,
    ...(active ? { Authorization: `Bearer ${active.accessToken}` } : {}),
    ...(workspaceId ? { 'X-Workspace-ID': workspaceId } : {}),
  };
}

async function errorFor(response: Response): Promise<AuditRequestError> {
  const payload = await response.json().catch(() => null) as { error?: { message?: string } } | null;
  return new AuditRequestError(
    payload?.error?.message ?? `Audit request failed (${response.status})`,
    response.status,
  );
}

function isHttpError(error: unknown): error is AuditRequestError {
  return error instanceof AuditRequestError;
}

export const auditApi = {
  async list(filters: AuditFilters = {}): Promise<AuditEvent[]> {
    try {
      const response = await fetch(`${API_URL}/audit/events${query(filters)}`, {
        credentials: 'include',
        headers: headers(),
      });
      if (!response.ok) throw await errorFor(response);
      return response.json() as Promise<AuditEvent[]>;
    } catch (error) {
      if (isHttpError(error)) throw error;
      // Standalone/demo previews have no durable audit backend. Never invent
      // security events; an empty trail is safer than fabricated audit history.
      return [];
    }
  },

  async exportCsv(filters: AuditFilters = {}): Promise<Blob> {
    try {
      const response = await fetch(`${API_URL}/audit/export${query(filters)}`, {
        credentials: 'include',
        headers: headers('text/csv'),
      });
      if (!response.ok) throw await errorFor(response);
      return response.blob();
    } catch (error) {
      if (isHttpError(error)) throw error;
      return new Blob([
        'created_at,workspace_id,actor_user_id,category,severity,outcome,action,entity_type,entity_id,request_id,ip_address\r\n',
      ], { type: 'text/csv;charset=utf-8' });
    }
  },
};
