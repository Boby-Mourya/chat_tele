import { readStorage } from '@/lib/storage';
import { activeWorkspaceId } from '@/lib/workspace-api';

export type CRMWorkflowStageStatus = 'ready' | 'warning' | 'blocked';
export type CRMWorkflowJourneyStage =
  | 'local_lead'
  | 'awaiting_routing'
  | 'in_progress'
  | 'provider_acknowledged'
  | 'verifying'
  | 'verified'
  | 'attention_required'
  | 'dead_letter';

export interface CRMWorkflowReadinessStage {
  id: string;
  label: string;
  description: string;
  status: CRMWorkflowStageStatus;
  detail: string;
  actionLabel?: string | null;
  actionPath?: string | null;
}

export interface CRMWorkflowReadiness {
  ready: boolean;
  stages: CRMWorkflowReadinessStage[];
}

export interface CRMWorkflowCounts {
  resolvedConversations: number;
  localLeads: number;
  leadsWithoutDelivery: number;
  totalDeliveries: number;
  inFlightDeliveries: number;
  verifiedDeliveries: number;
  attentionDeliveries: number;
  openDeadLetters: number;
  byStatus: Record<string, number>;
}

export interface CRMWorkflowConnection {
  id: string;
  name: string;
  provider: string;
  environment: string;
  status: string;
  credentialsConfigured: boolean;
  mappingConfigured: boolean;
  mappingStatus?: string | null;
  mappingVersion?: number | null;
  enabledRouteCount: number;
  autoSyncNewLeads: boolean;
  autoSyncUpdates: boolean;
  ready: boolean;
  lastHealthAt?: string | null;
  lastSuccessAt?: string | null;
  lastFailureAt?: string | null;
  lastError?: string | null;
}

export interface CRMWorkflowDelivery {
  id: string;
  connectionId: string;
  connectionName: string;
  provider: string;
  operation: string;
  status: string;
  verificationStatus: string;
  externalRecordId?: string | null;
  attemptCount: number;
  verificationAttemptCount: number;
  acknowledgedAt?: string | null;
  verifiedAt?: string | null;
  nextRetryAt?: string | null;
  nextVerificationAt?: string | null;
  lastErrorCode?: string | null;
  lastErrorMessage?: string | null;
  verificationErrorCode?: string | null;
  verificationErrorMessage?: string | null;
  deadLetterOpen: boolean;
  createdAt: string;
  updatedAt: string;
}

export interface CRMWorkflowJourney {
  leadId: string;
  conversationId?: string | null;
  conversationPublicId?: string | null;
  agentId: string;
  agentName: string;
  customerName?: string | null;
  email?: string | null;
  phone?: string | null;
  sourceChannel?: string | null;
  lifecycleStatus: string;
  qualificationStatus?: string | null;
  qualificationScore?: number | null;
  stage: CRMWorkflowJourneyStage;
  stageLabel: string;
  stageDetail: string;
  nextActionLabel?: string | null;
  nextActionPath?: string | null;
  delivery?: CRMWorkflowDelivery | null;
  createdAt: string;
  updatedAt: string;
}

export interface CRMWorkflow {
  generatedAt: string;
  workspaceId: string;
  readiness: CRMWorkflowReadiness;
  counts: CRMWorkflowCounts;
  connections: CRMWorkflowConnection[];
  recentJourneys: CRMWorkflowJourney[];
}

const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? '/api/v1';
const SESSION_KEY = 'northstar.session';

async function request<T>(path: string): Promise<T> {
  const accessToken = readStorage<{ accessToken?: string } | null>(SESSION_KEY, null)?.accessToken;
  const workspaceId = activeWorkspaceId();
  const response = await fetch(`${API_URL}${path}`, {
    credentials: 'include',
    headers: {
      Accept: 'application/json',
      ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
      ...(workspaceId ? { 'X-Workspace-ID': workspaceId } : {}),
    },
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as {
      detail?: unknown;
      error?: { message?: string };
    } | null;
    const detail = payload?.detail;
    const message = payload?.error?.message
      ?? (typeof detail === 'string' ? detail : undefined)
      ?? `CRM workflow request failed (${response.status})`;
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

export const crmWorkflowApi = {
  get: (limit = 25) => request<CRMWorkflow>(`/crm/workflow?limit=${limit}`),
};
