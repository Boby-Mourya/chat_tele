import { ApiError, AUTH_SESSION_EVENT, api, apiConfig } from '@/lib/api';
import { demoHelpArticle, demoHelpCategory, demoHelpHome, demoHelpSearch } from '@/lib/help-demo-data';
import { readStorage, writeStorage } from '@/lib/storage';
import { activeWorkspaceId } from '@/lib/workspace-api';
import type { Session } from '@/types';
import type {
  CreateHelpSupportRequestInput,
  HelpAiAnswer,
  HelpArticle,
  HelpCategory,
  HelpCategoryDetail,
  HelpFeedbackReason,
  HelpHome,
  HelpSearchPage,
  HelpSupportRequest,
} from '@/lib/help-types';

const TOKEN_KEY = 'northstar.session';
const SUPPORT_KEY = 'northstar.help.support';
const pause = (ms = 120) => new Promise((resolve) => setTimeout(resolve, ms));
const id = (prefix: string) => `${prefix}-${crypto.randomUUID?.() ?? Math.random().toString(36).slice(2)}`;

function currentSession(): Session | null { return api.auth.session(); }

function persistSession(value: Session): Session {
  const safe = { ...value };
  delete safe.refreshToken;
  writeStorage(TOKEN_KEY, safe);
  window.dispatchEvent(new Event(AUTH_SESSION_EVENT));
  return safe;
}

async function refreshSession(active: Session): Promise<Session> {
  const response = await fetch(`${apiConfig.baseUrl}/auth/refresh`, {
    method: 'POST',
    credentials: 'include',
    headers: { Accept: 'application/json', ...(active.refreshToken ? { 'Content-Type': 'application/json' } : {}) },
    body: active.refreshToken ? JSON.stringify({ refreshToken: active.refreshToken }) : undefined,
  });
  if (!response.ok) throw new ApiError('Your session has expired. Please sign in again.', 401);
  return persistSession(await response.json() as Session);
}

async function helpRequest<T>(path: string, init: RequestInit = {}, retried = false): Promise<T> {
  const active = currentSession();
  const workspaceId = activeWorkspaceId();
  const response = await fetch(`${apiConfig.baseUrl}${path}`, {
    ...init,
    credentials: init.credentials ?? 'include',
    headers: {
      Accept: 'application/json',
      ...(init.body ? { 'Content-Type': 'application/json' } : {}),
      ...(active ? { Authorization: `Bearer ${active.accessToken}` } : {}),
      ...(workspaceId ? { 'X-Workspace-ID': workspaceId } : {}),
      ...init.headers,
    },
  });
  if (response.status === 401 && active && !retried) {
    await refreshSession(active);
    return helpRequest<T>(path, init, true);
  }
  if (!response.ok) {
    let detail: unknown;
    try { detail = await response.json(); } catch { detail = await response.text().catch(() => undefined); }
    throw new ApiError(`Request failed (${response.status})`, response.status, detail);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

async function withFallback<T>(remote: () => Promise<T>, fallback: () => Promise<T>): Promise<T> {
  if (apiConfig.demoMode) {
    try { return await remote(); } catch (error) {
      if (error instanceof ApiError && [400, 401, 403, 409, 422].includes(error.status)) throw error;
      return fallback();
    }
  }
  return remote();
}

export const helpApi = {
  home: (context?: string) => withFallback(
    () => helpRequest<HelpHome>(`/help${context ? `?from=${encodeURIComponent(context)}` : ''}`),
    async () => { await pause(); return demoHelpHome(); },
  ),
  categories: () => withFallback(
    () => helpRequest<HelpCategory[]>('/help/categories'),
    async () => { await pause(); return demoHelpHome().categories; },
  ),
  category: (slug: string) => withFallback(
    () => helpRequest<HelpCategoryDetail>(`/help/categories/${encodeURIComponent(slug)}`),
    async () => { await pause(); const result = demoHelpCategory(slug); if (!result) throw new ApiError('Help category not found', 404); return result; },
  ),
  article: (slug: string) => withFallback(
    () => helpRequest<HelpArticle>(`/help/articles/${encodeURIComponent(slug)}`),
    async () => { await pause(); const result = demoHelpArticle(slug); if (!result) throw new ApiError('Help article not found', 404); return result; },
  ),
  search: (query: string, category?: string, page = 1, pageSize = 20) => withFallback(
    () => helpRequest<HelpSearchPage>(`/help/search?${new URLSearchParams({ q: query, page: String(page), page_size: String(pageSize), ...(category ? { category } : {}) }).toString()}`),
    async () => { await pause(); return demoHelpSearch(query); },
  ),
  feedback: (articleId: string, helpful: boolean, reason?: HelpFeedbackReason, comment?: string) => withFallback(
    () => helpRequest(`/help/articles/${articleId}/feedback`, { method: 'POST', body: JSON.stringify({ helpful, reason, comment }) }),
    async () => ({ articleId, helpful, reason: reason ?? null, comment: comment ?? null, updatedAt: new Date().toISOString() }),
  ),
  ask: (question: string) => withFallback(
    () => helpRequest<HelpAiAnswer>('/help/ask', { method: 'POST', body: JSON.stringify({ question }) }),
    async () => {
      await pause(260);
      const search = demoHelpSearch(question);
      return {
        answer: search.items.length ? `I found official Help guidance that may answer this question. Start with “${search.items[0]!.title}”.` : 'I could not find enough official Help information. Try a broader search or contact support.',
        citations: search.items.slice(0, 4), suggestedArticles: search.items.slice(0, 4), available: true,
      };
    },
  ),
  event: (eventType: 'search_click' | 'ai_citation_click', articleId: string, query?: string) => withFallback(
    () => helpRequest<void>('/help/events', { method: 'POST', body: JSON.stringify({ eventType, articleId, query }) }),
    async () => undefined,
  ),
  supportRequests: () => withFallback(
    () => helpRequest<HelpSupportRequest[]>('/help/support-requests'),
    async () => readStorage<HelpSupportRequest[]>(SUPPORT_KEY, []),
  ),
  supportRequest: (requestId: string) => withFallback(
    () => helpRequest<HelpSupportRequest>(`/help/support-requests/${requestId}`),
    async () => { const item = readStorage<HelpSupportRequest[]>(SUPPORT_KEY, []).find((entry) => entry.id === requestId); if (!item) throw new ApiError('Support request not found', 404); return item; },
  ),
  createSupportRequest: (input: CreateHelpSupportRequestInput) => withFallback(
    () => helpRequest<HelpSupportRequest>('/help/support-requests', { method: 'POST', body: JSON.stringify(input) }),
    async () => {
      await pause(220);
      const created: HelpSupportRequest = {
        id: id('help-request'), category: input.category, subject: input.subject, message: input.message, status: 'submitted', contextPath: input.contextPath,
        requesterEmail: currentSession()?.user.email ?? 'demo@northstar.ai', supportDestination: 'support@northstar.ai', diagnostics: input.diagnostics ?? {},
        createdAt: new Date().toISOString(), updatedAt: new Date().toISOString(),
      };
      const items = readStorage<HelpSupportRequest[]>(SUPPORT_KEY, []); items.unshift(created); writeStorage(SUPPORT_KEY, items); return created;
    },
  ),
};
