import type { Session } from '@/types';
import { readStorage } from '@/lib/storage';
import { activeWorkspaceId } from '@/lib/workspace-api';

export interface EnrollmentReadiness {
  endpoint?: string;
  whatsappConnected: boolean;
  verifiedStudentNumbers: number;
  pendingStudentNumbers: number;
  knowledgeSources: number;
  aiProviderConfigured: boolean;
}
export async function enrollmentReadiness(agentId: string): Promise<EnrollmentReadiness> {
  const base = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? '/api/v1';
  const session = readStorage<Session | null>('northstar.session', null);
  const workspaceId = activeWorkspaceId();
  const response = await fetch(`${base}/education/agents/${agentId}/enrollment-events/readiness`, { credentials: 'include', headers: {
    ...(session ? { Authorization: `Bearer ${session.accessToken}` } : {}), ...(workspaceId ? { 'X-Workspace-ID': workspaceId } : {}),
  } });
  if (!response.ok) throw new Error('Could not check bot setup. Refresh to try again.');
  return response.json();
}
