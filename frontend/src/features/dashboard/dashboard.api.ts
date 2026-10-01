import { activeWorkspaceId, workspacePresentationKey, WorkspaceRequestError } from '@/lib/workspace-api';
import { readStorage } from '@/lib/storage';
import type { WorkspaceDashboardRuntime } from './dashboard.types';

const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? '/api/v1';
const SESSION_KEY = 'northstar.session';

function storedToken(): string | undefined {
  return readStorage<{ accessToken?: string } | null>(SESSION_KEY, null)?.accessToken;
}

export async function loadWorkspaceDashboardRuntime(signal?: AbortSignal): Promise<WorkspaceDashboardRuntime> {
  const identity = workspacePresentationKey();
  const workspaceId = activeWorkspaceId();
  const token = storedToken();
  const response = await fetch(`${API_URL}/workspace/settings/runtime-dashboard`, {
    method: 'GET',
    signal,
    cache: 'no-store',
    credentials: 'include',
    headers: {
      Accept: 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(workspaceId ? { 'X-Workspace-ID': workspaceId } : {}),
    },
  });
  const payload: unknown = await response.json().catch(() => undefined);
  if (identity !== workspacePresentationKey() || workspaceId !== activeWorkspaceId()) {
    throw new DOMException('Workspace context changed', 'AbortError');
  }
  if (!response.ok) {
    const value = payload as { error?: { message?: string }; detail?: unknown } | undefined;
    throw new WorkspaceRequestError(
      value?.error?.message ?? (typeof value?.detail === 'string' ? value.detail : `Dashboard request failed (${response.status})`),
      response.status,
    );
  }
  return payload as WorkspaceDashboardRuntime;
}
