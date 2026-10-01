import { readStorage, writeStorage } from '@/lib/storage';
import { activeWorkspaceId } from '@/lib/workspace-api';

export const WORKSPACE_API_KEY_SCOPES = [
  'workspace:read',
  'conversations:read',
  'conversations:write',
  'contacts:read',
  'leads:write',
  'agents:read',
  'analytics:read',
  'webhooks:manage',
] as const;
export type WorkspaceAPIKeyScope = typeof WORKSPACE_API_KEY_SCOPES[number];

export interface WorkspaceAPIKey {
  id: string;
  name: string;
  prefix: string;
  scopes: WorkspaceAPIKeyScope[];
  createdAt: string;
  lastUsedAt?: string | null;
}

export interface WorkspaceAPIKeyCreated extends WorkspaceAPIKey {
  secret: string;
}

const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? '/api/v1';
const DEMO_MODE = (import.meta.env.VITE_DEMO_MODE as string | undefined) === 'true';
const SESSION_KEY = 'northstar.session';
const LOCAL_KEYS_KEY = 'northstar.workspace.api-keys';

class WorkspaceAPIKeyRequestError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = 'WorkspaceAPIKeyRequestError';
  }
}

function bearer(): string | undefined {
  return readStorage<{ accessToken?: string } | null>(SESSION_KEY, null)?.accessToken;
}

async function remote<T>(path: string, method: 'GET' | 'POST' | 'DELETE', body?: unknown): Promise<T> {
  const token = bearer();
  const workspaceId = activeWorkspaceId();
  const response = await fetch(`${API_URL}${path}`, {
    method,
    credentials: 'include',
    headers: {
      Accept: 'application/json',
      ...(body ? { 'Content-Type': 'application/json' } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(workspaceId ? { 'X-Workspace-ID': workspaceId } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  const payload = response.status === 204 ? undefined : await response.json().catch(() => null);
  if (!response.ok) {
    const error = payload as { error?: { message?: string }; detail?: unknown } | null;
    throw new WorkspaceAPIKeyRequestError(
      error?.error?.message ?? (typeof error?.detail === 'string' ? error.detail : `API key request failed (${response.status})`),
      response.status,
    );
  }
  if (response.status === 204) return undefined as T;
  return payload as T;
}

function shouldUseDemoFallback(error: unknown): boolean {
  if (!DEMO_MODE) return false;
  return !(error instanceof WorkspaceAPIKeyRequestError && error.status >= 400 && error.status < 500);
}

function localKeys(): WorkspaceAPIKey[] {
  return readStorage<WorkspaceAPIKey[]>(LOCAL_KEYS_KEY, []);
}

function createLocalKey(name: string, scopes: WorkspaceAPIKeyScope[]): WorkspaceAPIKeyCreated {
  const secret = `nsk_live_${crypto.randomUUID().replaceAll('-', '')}${crypto.randomUUID().replaceAll('-', '')}`;
  const key: WorkspaceAPIKey = {
    id: crypto.randomUUID(),
    name,
    prefix: secret.slice(0, 16),
    scopes,
    createdAt: new Date().toISOString(),
    lastUsedAt: null,
  };
  writeStorage(LOCAL_KEYS_KEY, [key, ...localKeys()]);
  return { ...key, secret };
}

export const workspaceAPIKeyApi = {
  async list(): Promise<WorkspaceAPIKey[]> {
    try {
      return await remote<WorkspaceAPIKey[]>('/workspace/api-keys', 'GET');
    } catch (error) {
      if (!shouldUseDemoFallback(error)) throw error;
      return localKeys();
    }
  },

  async create(name: string, scopes: WorkspaceAPIKeyScope[]): Promise<WorkspaceAPIKeyCreated> {
    const normalizedName = name.trim().replace(/\s+/g, ' ');
    if (normalizedName.length < 2) throw new Error('API key name must be at least 2 characters');
    if (scopes.length === 0) throw new Error('Select at least one API key scope');
    try {
      return await remote<WorkspaceAPIKeyCreated>('/workspace/api-keys', 'POST', { name: normalizedName, scopes });
    } catch (error) {
      if (!shouldUseDemoFallback(error)) throw error;
      return createLocalKey(normalizedName, scopes);
    }
  },

  async revoke(id: string): Promise<void> {
    try {
      await remote<void>(`/workspace/api-keys/${encodeURIComponent(id)}`, 'DELETE');
    } catch (error) {
      if (!shouldUseDemoFallback(error)) throw error;
      writeStorage(LOCAL_KEYS_KEY, localKeys().filter((item) => item.id !== id));
    }
  },
};
