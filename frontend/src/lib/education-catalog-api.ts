import { readStorage } from '@/lib/storage';
import { activeWorkspaceId } from '@/lib/workspace-api';

export interface EducationCurriculum {
  id: string;
  courseId: string;
  version: string;
  name: string;
  status: 'active' | 'archived';
}

export interface EducationPaper {
  id: string;
  courseId: string;
  curriculumId: string;
  code: string;
  name: string;
  status: 'active' | 'archived';
}

const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? '/api/v1';
const SESSION_KEY = 'northstar.session';

async function get<T>(path: string): Promise<T> {
  const token = readStorage<{ accessToken?: string } | null>(SESSION_KEY, null)?.accessToken;
  const workspaceId = activeWorkspaceId();
  const response = await fetch(`${API_URL}${path}`, {
    credentials: 'include',
    headers: {
      Accept: 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(workspaceId ? { 'X-Workspace-ID': workspaceId } : {}),
    },
  });
  if (!response.ok) throw new Error(`Education catalog request failed (${response.status})`);
  return response.json() as Promise<T>;
}

export const educationCatalogApi = {
  curricula: (courseId?: string) => get<EducationCurriculum[]>(
    `/education/curricula?status=active${courseId ? `&course_id=${encodeURIComponent(courseId)}` : ''}`,
  ),
  papers: (curriculumId?: string) => get<EducationPaper[]>(
    `/education/papers?status=active${curriculumId ? `&curriculum_id=${encodeURIComponent(curriculumId)}` : ''}`,
  ),
};
