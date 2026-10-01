import { ApiError } from '@/lib/api';
import { readStorage } from '@/lib/storage';
import { activeWorkspaceId } from '@/lib/workspace-api';
import type { Session } from '@/types';

const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? '/api/v1';
const SESSION_KEY = 'northstar.session';
export type WorkflowPurpose = 'support' | 'lead_generation' | 'education';
export type WorkflowFormat = 'text' | 'buttons' | 'list' | 'table' | 'image' | 'video' | 'audio' | 'document' | 'sticker' | 'location' | 'contact' | 'cta_url' | 'flow' | 'product' | 'product_list' | 'catalog' | 'template';
export type WorkflowTrigger = 'command' | 'contains' | 'condition' | 'fallback';
export interface WorkflowCondition { field: 'message' | 'channel'; operator: 'equals' | 'contains' | 'not_contains' | 'starts_with'; value: string }
export type WorkflowRepeatPolicy = 'every_match' | 'once_per_conversation' | 'once_per_24_hours' | 'once_per_calendar_day';
export interface WorkflowStep { id: string; name: string; triggerType: WorkflowTrigger; triggerValue: string; messageFormat: WorkflowFormat; message: string; buttons: Array<{ id: string; title: string }>; table: { columns: string[]; rows: string[][] } | null; template: { name: string; language: string; preview: string } | null; config: Record<string, unknown>; condition: WorkflowCondition | null; trueStepId: string | null; falseStepId: string | null; nextStepId: string | null; positionX: number; positionY: number; botBehavior: 'complete' | 'wait_for_next_trigger'; waitingMessage: string; waitRepeatCount: number; repeatPolicy: WorkflowRepeatPolicy; maxSends: number | null; cooldownMinutes: number; calendarTimezone: string; enabled: boolean }
export interface BotWorkflow { id: string; agentId: string; name: string; purpose: WorkflowPurpose; status: 'draft' | 'active'; steps: WorkflowStep[]; createdAt: string; updatedAt: string }
export type BotWorkflowSave = Pick<BotWorkflow, 'name' | 'purpose' | 'status' | 'steps'>;
export interface BotWorkflowTemplate { key: string; name: string; purpose: WorkflowPurpose; description: string; workflow: BotWorkflowSave }

function headers(): HeadersInit { const session = readStorage<Session | null>(SESSION_KEY, null); const workspace = activeWorkspaceId(); return { Accept: 'application/json', 'Content-Type': 'application/json', ...(session ? { Authorization: `Bearer ${session.accessToken}` } : {}), ...(workspace ? { 'X-Workspace-ID': workspace } : {}) }; }
async function request<T>(path: string, init?: RequestInit): Promise<T> { const response = await fetch(`${API_URL}${path}`, { credentials: 'include', ...init, headers: { ...headers(), ...init?.headers } }); if (!response.ok) { const body = await response.json().catch(() => null) as { detail?: string; error?: { message?: string } } | null; throw new ApiError(body?.error?.message ?? body?.detail ?? `Workflow request failed (${response.status})`, response.status); } return response.status === 204 ? undefined as T : response.json() as Promise<T>; }
export const botWorkflowApi = {
  list: () => request<BotWorkflow[]>('/bot-workflows'),
  get: (agentId: string) => request<BotWorkflow>(`/bot-workflows/${agentId}`),
  templates: () => request<BotWorkflowTemplate[]>('/bot-workflows/templates'),
  applyTemplate: (agentId: string, templateKey: string) => request<BotWorkflow>(`/bot-workflows/${agentId}/templates/${templateKey}`, { method: 'POST' }),
  save: (agentId: string, value: BotWorkflowSave) => request<BotWorkflow>(`/bot-workflows/${agentId}`, { method: 'PUT', body: JSON.stringify(value) }),
  remove: (agentId: string) => request<void>(`/bot-workflows/${agentId}`, { method: 'DELETE' }),
};
