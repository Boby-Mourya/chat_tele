import { readStorage } from '@/lib/storage';
import { activeWorkspaceId, workspacePresentationKey, workspaceSessionScope } from '@/lib/workspace-api';

export interface PendingStarterClone {
  schemaVersion: 1; identity: string; workspaceId: string; catalogId: string;
  catalogVersion: number; name: string; idempotencyKey: string;
}
export interface StarterCloneResult {
  requestId: string; catalogId: string; catalogVersion: number; agentId: string;
  workspaceId: string; name: string; purpose: 'support'; initialStatus: 'draft';
  sample: true; createdAt: string; replayed: boolean;
}
export class StarterCloneError extends Error {
  constructor(message: string, readonly status: number, readonly ambiguous = false) {
    super(message); this.name = 'StarterCloneError';
  }
}
const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? '/api/v1';
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const ITEM_PATTERN = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const sessionToken = () => readStorage<{ accessToken?: string } | null>('northstar.session', null)?.accessToken;
function context(catalogId: string) {
  if (!ITEM_PATTERN.test(catalogId) || catalogId.length > 100) throw new StarterCloneError('Invalid starter item', 422);
  const token = sessionToken();
  const workspaceId = activeWorkspaceId();
  if (!token || token.startsWith('demo') || !workspaceId || !UUID_PATTERN.test(workspaceId)) {
    throw new StarterCloneError('Select an authenticated workspace before copying a template.', 401);
  }
  return { identity: workspacePresentationKey(), workspaceId,
    key: `northstar.starter-copy:${workspaceSessionScope()}:${workspaceId}:${catalogId}` };
}
function pending(catalogId: string): PendingStarterClone | null {
  const scope = context(catalogId);
  let raw: string | null;
  try { raw = sessionStorage.getItem(scope.key); }
  catch { throw new StarterCloneError('Browser storage is required to recover a template-copy request safely.', 503); }
  if (raw === null) return null;
  let value: PendingStarterClone;
  try { value = JSON.parse(raw) as PendingStarterClone; }
  catch { throw new StarterCloneError('The saved copy request is damaged. Do not resend an unknown request.', 409); }
  if (!value || value.schemaVersion !== 1 || value.identity !== scope.identity || value.workspaceId !== scope.workspaceId
      || value.catalogId !== catalogId || !UUID_PATTERN.test(value.idempotencyKey)
      || !Number.isSafeInteger(value.catalogVersion) || value.catalogVersion < 1
      || typeof value.name !== 'string' || value.name.length < 2 || value.name.length > 120) {
    throw new StarterCloneError('The saved copy request no longer matches this access context. Check your existing agents before creating another copy.', 409);
  }
  return value;
}
function prepare(catalogId: string, catalogVersion: number, name: string): PendingStarterClone {
  const scope = context(catalogId);
  const normalized = name.trim().replace(/\s+/g, ' ');
  if (!Number.isSafeInteger(catalogVersion) || catalogVersion < 1 || normalized.length < 2 || normalized.length > 120
      || /[\p{Cc}\p{Cf}\p{Cs}\p{Co}\p{Cn}]/u.test(name)) {
    throw new StarterCloneError('Enter a valid name of 2–120 characters and reload an outdated catalog.', 422);
  }
  const previous = pending(catalogId);
  // Name edits keep the SAME request ID. A completed request cannot be turned
  // into a second copy merely by editing the form after a network interruption.
  const value: PendingStarterClone = { schemaVersion: 1, identity: scope.identity, workspaceId: scope.workspaceId,
    catalogId, catalogVersion, name: normalized, idempotencyKey: previous?.idempotencyKey ?? crypto.randomUUID() };
  try {
    sessionStorage.setItem(scope.key, JSON.stringify(value));
    if (sessionStorage.getItem(scope.key) !== JSON.stringify(value)) throw new Error('Storage write failed');
  } catch { throw new StarterCloneError('The recovery request could not be saved. No copy was submitted.', 503); }
  return value;
}
function checkContext(value: PendingStarterClone, signal?: AbortSignal) {
  if (signal?.aborted || value.identity !== workspacePresentationKey() || value.workspaceId !== activeWorkspaceId()) {
    throw new DOMException('Account or workspace changed; no response was applied', 'AbortError');
  }
}
function parseResult(raw: unknown, request: PendingStarterClone, submitting: boolean): StarterCloneResult {
  const value = raw as Partial<StarterCloneResult> | null;
  if (!value || value.requestId !== request.idempotencyKey || value.workspaceId !== request.workspaceId
      || value.catalogId !== request.catalogId || typeof value.agentId !== 'string' || !UUID_PATTERN.test(value.agentId)
      || typeof value.name !== 'string' || value.name.length < 2 || value.name.length > 120
      || !Number.isSafeInteger(value.catalogVersion) || Number(value.catalogVersion) < 1
      || value.purpose !== 'support' || value.initialStatus !== 'draft' || value.sample !== true
      || typeof value.replayed !== 'boolean' || typeof value.createdAt !== 'string' || !Number.isFinite(Date.parse(value.createdAt))
      || (submitting && (value.name !== request.name || value.catalogVersion !== request.catalogVersion))) {
    throw new StarterCloneError('The server returned an invalid copy result. Check the saved request before retrying.', 502, true);
  }
  return value as StarterCloneResult;
}
async function request(value: PendingStarterClone, submitting: boolean, signal?: AbortSignal): Promise<StarterCloneResult> {
  checkContext(value, signal);
  const token = sessionToken();
  if (!token) throw new StarterCloneError('Sign in to continue.', 401);
  const path = submitting ? `/${encodeURIComponent(value.catalogId)}/clone`
    : `/clone-requests/${encodeURIComponent(value.idempotencyKey)}`;
  let response: Response;
  try {
    response = await fetch(`${API_URL}/starter-content${path}`, {
      method: submitting ? 'POST' : 'GET', credentials: 'include', cache: 'no-store', signal,
      headers: { Accept: 'application/json', Authorization: `Bearer ${token}`, 'X-Workspace-ID': value.workspaceId,
        ...(submitting ? { 'Content-Type': 'application/json' } : {}) },
      body: submitting ? JSON.stringify({ idempotencyKey: value.idempotencyKey, catalogVersion: value.catalogVersion, name: value.name }) : undefined,
    });
  } catch (error) {
    checkContext(value, signal);
    throw new StarterCloneError(error instanceof Error ? error.message : 'Template service unavailable', 503, submitting);
  }
  const body: unknown = await response.json().catch(() => null);
  checkContext(value, signal);
  if (token !== sessionToken()) throw new StarterCloneError('The session renewed. Check the saved copy request before retrying.', 409, submitting);
  if (!response.ok) {
    const error = body as { detail?: unknown; error?: { message?: unknown } } | null;
    const detail = error?.error?.message ?? error?.detail;
    throw new StarterCloneError(typeof detail === 'string' ? detail : `Template request failed (${response.status})`, response.status, submitting && response.status >= 500);
  }
  return parseResult(body, value, submitting);
}
function startAnother(catalogId: string, completedRequestId: string): void {
  const scope = context(catalogId);
  const saved = pending(catalogId);
  if (!saved || saved.idempotencyKey !== completedRequestId) throw new StarterCloneError('The saved request changed. Check its result first.', 409);
  sessionStorage.removeItem(scope.key);
}
export const starterContentApi = {
  pending, prepare, startAnother,
  submit: (value: PendingStarterClone, signal?: AbortSignal) => request(value, true, signal),
  result: (value: PendingStarterClone, signal?: AbortSignal) => request(value, false, signal),
};
