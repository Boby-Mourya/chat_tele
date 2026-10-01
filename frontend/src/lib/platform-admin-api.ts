import { activeWorkspaceId } from '@/lib/workspace-api';
import { readStorage } from '@/lib/storage';
import type { Session } from '@/types';

export interface PlatformAdminAccess {
  authorized: boolean;
  email: string;
}

export interface PlatformAdminPermissions {
  email: string;
  permissions: string[];
}

export interface PlatformOperator {
  userId: string;
  name: string;
  email: string;
  role: 'owner' | 'operations' | 'billing' | 'support' | 'auditor' | string;
  permissions: string[];
  isActive: boolean;
  createdAt: string;
}

export interface PlatformOperations {
  status: 'healthy' | 'degraded' | string;
  failedIngestionJobs: number;
  unpublishedOutboxEvents: number;
  oldestUnpublishedEventAt: string | null;
  quarantinedEvents: number;
  channelIssues: number;
  crmConnectionIssues: number;
  crmDeliveryIssues: number;
  openCrmDeadLetters: number;
  criticalAuditEvents24h: number;
}

export interface PlatformOverview {
  tenants: number;
  workspaces: number;
  users: number;
  agents: number;
  conversations: number;
  leads: number;
  subscriptions: {
    trial: number;
    active: number;
    pastDue: number;
    suspended: number;
    cancelled: number;
  };
  operations: PlatformOperations;
}

export interface PlatformTenantSummary {
  id: string;
  name: string;
  slug: string;
  plan: string;
  subscriptionStatus: string;
  workspaceCount: number;
  memberCount: number;
  agentCount: number;
  conversationCount: number;
  leadCount: number;
  channelIssues: number;
  crmIssues: number;
  createdAt: string;
}

export interface PlatformWorkspaceSummary {
  id: string;
  name: string;
  slug: string;
  status: string;
  memberCount: number;
  agentCount: number;
  conversationCount: number;
  leadCount: number;
  createdAt: string;
}

export interface PlatformEntitlement {
  plan: string;
  workspaceLimit: number | null;
  agentLimit: number | null;
  memberLimit: number | null;
  conversationLimitMonthly: number | null;
  tokenLimitMonthly: number | null;
  storageLimitBytes: number | null;
  allowedChannels: string[];
  crmEnabled: boolean;
  apiEnabled: boolean;
  whiteLabelEnabled: boolean;
  customDomainEnabled: boolean;
  brandedEmailEnabled: boolean;
  removePlatformMarkEnabled: boolean;
}

export interface PlatformConfiguration {
  appEnv: string;
  appApiPrefix: string;
  backgroundDispatchEnabled: boolean;
  kafkaEnabled: boolean;
  educationMultiCourseEnabled: boolean;
  requireNvidia: boolean;
  allowDeterministicEmbeddings: boolean;
  platformImpersonationTtlMinutes: number;
  rateLimitFailOpen: boolean;
  retrievalCandidateLimit: number;
  retrievalContextLimit: number;
  knowledgeMaxPdfPages: number;
  knowledgeMaxChunks: number;
}

export interface PlatformTenantUser {
  id: string;
  name: string;
  email: string;
  role: string;
  isActive: boolean;
  createdAt: string;
}

export interface PlatformAuditSummary {
  id: string;
  action: string;
  entityType: string;
  entityId: string;
  category: string;
  severity: string;
  outcome: string;
  workspaceId: string | null;
  createdAt: string;
}

export interface PlatformTenantDetail extends PlatformTenantSummary {
  provider: string | null;
  currentPeriodEnd: string | null;
  cancelAtPeriodEnd: boolean;
  workspaces: PlatformWorkspaceSummary[];
  users: PlatformTenantUser[];
  recentAudit: PlatformAuditSummary[];
}

export interface PlatformImpersonationSession {
  accessToken: string;
  expiresAt: string;
  tenantId: string;
  workspaceId: string;
  userId: string;
  impersonationId: string;
}

export interface PlatformTenantList {
  items: PlatformTenantSummary[];
  total: number;
  limit: number;
  offset: number;
}

const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? '/api/v1';
const SESSION_KEY = 'northstar.session';

class PlatformAdminRequestError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = 'PlatformAdminRequestError';
  }
}

function headers(path: string): Record<string, string> {
  const session = readStorage<Session | null>(SESSION_KEY, null);
  const workspaceId = activeWorkspaceId();
  const platformScope = path.startsWith('/platform-admin');
  return {
    Accept: 'application/json',
    ...(session ? { Authorization: `Bearer ${session.accessToken}` } : {}),
    ...(!platformScope && workspaceId ? { 'X-Workspace-ID': workspaceId } : {}),
  };
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    credentials: 'include',
    headers: { ...headers(path), ...(init.body ? { 'Content-Type': 'application/json' } : {}), ...init.headers },
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { error?: { message?: string } } | null;
    throw new PlatformAdminRequestError(
      payload?.error?.message ?? `Platform admin request failed (${response.status})`,
      response.status,
    );
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const platformAdminApi = {
  async canAccess(): Promise<boolean> {
    try {
      const value = await request<PlatformAdminAccess>('/platform-admin/access');
      return value.authorized;
    } catch (error) {
      if (error instanceof PlatformAdminRequestError && [401, 403].includes(error.status)) return false;
      throw error;
    }
  },

  access(): Promise<PlatformAdminAccess> {
    return request<PlatformAdminAccess>('/platform-admin/access');
  },

  permissions(): Promise<PlatformAdminPermissions> {
    return request<PlatformAdminPermissions>('/platform-admin/permissions');
  },

  operators(): Promise<PlatformOperator[]> {
    return request<PlatformOperator[]>('/platform-admin/operators');
  },

  updateOperator(userId: string, value: { role: string; permissions: string[]; isActive: boolean; reason: string }): Promise<PlatformOperator> {
    return request<PlatformOperator>(`/platform-admin/operators/${encodeURIComponent(userId)}`, {
      method: 'PUT', body: JSON.stringify(value),
    });
  },

  overview(): Promise<PlatformOverview> {
    return request<PlatformOverview>('/platform-admin/overview');
  },

  entitlements(): Promise<PlatformEntitlement[]> {
    return request<PlatformEntitlement[]>('/platform-admin/entitlements');
  },

  configuration(): Promise<PlatformConfiguration> {
    return request<PlatformConfiguration>('/platform-admin/configuration');
  },

  tenants(search = '', limit = 50, offset = 0): Promise<PlatformTenantList> {
    const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    if (search.trim()) params.set('search', search.trim());
    return request<PlatformTenantList>(`/platform-admin/tenants?${params.toString()}`);
  },

  tenant(tenantId: string): Promise<PlatformTenantDetail> {
    return request<PlatformTenantDetail>(`/platform-admin/tenants/${encodeURIComponent(tenantId)}`);
  },

  updateLifecycle(tenantId: string, action: 'suspend' | 'reactivate', reason: string): Promise<PlatformTenantDetail> {
    return request<PlatformTenantDetail>(`/platform-admin/tenants/${encodeURIComponent(tenantId)}/lifecycle`, {
      method: 'PATCH', body: JSON.stringify({ action, reason }),
    });
  },

  updateSubscription(tenantId: string, value: { plan: string; status: string; reason: string }): Promise<PlatformTenantDetail> {
    return request<PlatformTenantDetail>(`/platform-admin/tenants/${encodeURIComponent(tenantId)}/subscription`, {
      method: 'PATCH', body: JSON.stringify(value),
    });
  },

  startImpersonation(value: { tenantId: string; workspaceId: string; userId: string; reason: string }): Promise<PlatformImpersonationSession> {
    return request<PlatformImpersonationSession>('/platform-admin/impersonation', {
      method: 'POST', body: JSON.stringify(value),
    });
  },

  endImpersonation(impersonationId: string, reason: string): Promise<void> {
    return request<void>(`/platform-admin/impersonation/${encodeURIComponent(impersonationId)}/end`, {
      method: 'POST', body: JSON.stringify({ reason }),
    });
  },
};
