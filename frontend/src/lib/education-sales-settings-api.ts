import { ApiError } from '@/lib/api';
import { readStorage } from '@/lib/storage';
import { activeWorkspaceId } from '@/lib/workspace-api';
import type { Session } from '@/types';

export interface EducationSalesRoutingSettings {
  createUpsellLeads: boolean;
}

const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? '/api/v1';
const SESSION_KEY = 'northstar.session';

function headers(withBody = false): HeadersInit {
  const session = readStorage<Session | null>(SESSION_KEY, null);
  const workspaceId = activeWorkspaceId();
  return {
    Accept: 'application/json',
    ...(withBody ? { 'Content-Type': 'application/json' } : {}),
    ...(session ? { Authorization: `Bearer ${session.accessToken}` } : {}),
    ...(workspaceId ? { 'X-Workspace-ID': workspaceId } : {}),
  };
}

async function request(
  method: 'GET' | 'PATCH',
  body?: EducationSalesRoutingSettings,
): Promise<EducationSalesRoutingSettings> {
  const response = await fetch(`${API_URL}/education/settings/sales-routing`, {
    method,
    credentials: 'include',
    headers: headers(Boolean(body)),
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) {
    throw new ApiError(`Education sales routing request failed (${response.status})`, response.status);
  }
  return response.json() as Promise<EducationSalesRoutingSettings>;
}

export const educationSalesSettingsApi = {
  get(): Promise<EducationSalesRoutingSettings> {
    return request('GET');
  },
  update(settings: EducationSalesRoutingSettings): Promise<EducationSalesRoutingSettings> {
    return request('PATCH', settings);
  },
};
