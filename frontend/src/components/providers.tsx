import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { CheckCircle2, CircleAlert, Info, X } from 'lucide-react';
import { api, AUTH_SESSION_EVENT } from '@/lib/api';
import { isMFAChallenge, mfaApi, type LoginResult, type MFAFactor } from '@/lib/mfa-api';
import { signupApi, type SignupInput } from '@/lib/signup-api';
import { activeWorkspaceId, persistActiveWorkspace, workspaceApi, workspacePresentationKey, retryableWorkspaceRead, type WorkspaceCreate, type WorkspaceSettings } from '@/lib/workspace-api';
import type { Session } from '@/types';

const SUPPORT_RETURN_SESSION_KEY = 'northstar.support.return-session';
const SUPPORT_RETURN_WORKSPACE_KEY = 'northstar.support.return-workspace';

interface AuthContextValue {
  session: Session | null; login: (email: string, password: string) => Promise<LoginResult>;
  completeMFA: (challengeToken: string, factor: MFAFactor) => Promise<Session>;
  signup: (input: SignupInput) => Promise<Session>; logout: () => Promise<void>;
  assumeSession: (next: Session) => void; restoreSession: () => boolean;
}
const AuthContext = createContext<AuthContextValue | null>(null);
export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(() => api.auth.session());
  useEffect(() => {
    const syncSession = () => setSession(api.auth.session());
    window.addEventListener(AUTH_SESSION_EVENT, syncSession); window.addEventListener('storage', syncSession);
    return () => { window.removeEventListener(AUTH_SESSION_EVENT, syncSession); window.removeEventListener('storage', syncSession); };
  }, []);
  const login = useCallback(async (email: string, password: string) => {
    const next = await mfaApi.login(email, password); if (!isMFAChallenge(next)) setSession(next); return next;
  }, []);
  const completeMFA = useCallback(async (challengeToken: string, factor: MFAFactor) => {
    const next = await mfaApi.verifyChallenge(challengeToken, factor); setSession(next); return next;
  }, []);
  const signup = useCallback(async (input: SignupInput) => { const next = await signupApi.signup(input); setSession(next); return next; }, []);
  const logout = useCallback(async () => { await api.auth.logout(); setSession(null); }, []);
  const assumeSession = useCallback((next: Session) => {
    const current = api.auth.session();
    if (current && !current.impersonation) {
      try { sessionStorage.setItem(SUPPORT_RETURN_SESSION_KEY, JSON.stringify(current)); } catch { /* Storage may be unavailable. */ }
      const workspaceId = activeWorkspaceId();
      if (workspaceId) { try { sessionStorage.setItem(SUPPORT_RETURN_WORKSPACE_KEY, workspaceId); } catch { /* Storage may be unavailable. */ } }
    }
    api.auth.adopt(next);
    setSession(next);
  }, []);
  const restoreSession = useCallback(() => {
    try {
      const raw = sessionStorage.getItem(SUPPORT_RETURN_SESSION_KEY);
      if (!raw) return false;
      const original = JSON.parse(raw) as Session;
      sessionStorage.removeItem(SUPPORT_RETURN_SESSION_KEY);
      const workspaceId = sessionStorage.getItem(SUPPORT_RETURN_WORKSPACE_KEY);
      if (workspaceId) { persistActiveWorkspace(workspaceId); sessionStorage.removeItem(SUPPORT_RETURN_WORKSPACE_KEY); }
      api.auth.adopt(original);
      setSession(original);
      return true;
    } catch { return false; }
  }, []);
  const value = useMemo(() => ({ session, login, completeMFA, signup, logout, assumeSession, restoreSession }), [session, login, completeMFA, signup, logout, assumeSession, restoreSession]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
export function useAuth(): AuthContextValue { const value = useContext(AuthContext); if (!value) throw new Error('useAuth must be used inside AuthProvider'); return value; }

interface WorkspaceContextValue {
  workspaces: WorkspaceSettings[]; activeWorkspace: WorkspaceSettings | null; loading: boolean; error: string | null; refreshing?: boolean; refreshError?: string | null;
  selectWorkspace: (workspaceId: string) => void; refreshWorkspaces: () => Promise<void>;
  createWorkspace: (input: WorkspaceCreate) => Promise<WorkspaceSettings>;
}
const WorkspaceContext = createContext<WorkspaceContextValue | null>(null);
export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const { session } = useAuth();
  const [workspaces, setWorkspaces] = useState<WorkspaceSettings[]>([]);
  const [activeWorkspace, setActiveWorkspace] = useState<WorkspaceSettings | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loadedFor, setLoadedFor] = useState('');
  const [refreshError, setRefreshError] = useState<string | null>(null);
  const acceptedContext = useRef('');
  const requestController = useRef<AbortController | null>(null);
  const generation = useRef(0);
  const scope = workspacePresentationKey();
  const verified = !!session && session.user.emailVerified !== false;
  const load = useCallback(async () => {
    const serial = ++generation.current; const requestedScope = workspacePresentationKey();
    requestController.current?.abort();
    if (!verified || scope !== requestedScope) {
      setWorkspaces([]); setActiveWorkspace(null); setPending(false); setError(null); setLoadedFor(requestedScope); setRefreshError(null); acceptedContext.current = requestedScope; return;
    }
    const controller = new AbortController(); requestController.current = controller;
    setPending(true); setError(null); setRefreshError(null);
    try {
      const values = await workspaceApi.list(controller.signal);
      if (serial !== generation.current || requestedScope !== workspacePresentationKey()) return;
      const selected = values.find((item) => item.id === activeWorkspaceId()) ?? values[0] ?? null;
      if (selected) persistActiveWorkspace(selected.id);
      acceptedContext.current = requestedScope;
      setWorkspaces(values); setActiveWorkspace(selected); setLoadedFor(requestedScope);
    } catch (reason) {
      if (serial === generation.current && requestedScope === workspacePresentationKey()) {
        const message = reason instanceof Error ? reason.message : 'Workspaces could not be loaded';
        if (acceptedContext.current === requestedScope && retryableWorkspaceRead(reason)) {
          setRefreshError(message); // Keep the currently authorized view during a transient background outage.
        } else {
          acceptedContext.current = '';
          setWorkspaces([]); setActiveWorkspace(null); setLoadedFor(requestedScope); setError(message);
        }
      }
      throw reason;
    } finally { if (serial === generation.current) setPending(false); }
  }, [scope, verified]);
  useEffect(() => { void load().catch(() => undefined); return () => { generation.current += 1; requestController.current?.abort(); }; }, [load]);
  useEffect(() => {
    const changed = (event: Event) => {
      const value = (event as CustomEvent<WorkspaceSettings>).detail;
      if (loadedFor !== workspacePresentationKey() || !value?.id) return;
      setWorkspaces((old) => old.map((item) => item.id === value.id && item.tenantId === value.tenantId ? value : item));
      setActiveWorkspace((old) => old?.id === value.id && old.tenantId === value.tenantId ? value : old);
    };
    window.addEventListener('northstar:workspace-changed', changed);
    return () => window.removeEventListener('northstar:workspace-changed', changed);
  }, [loadedFor]);
  const selectWorkspace = useCallback((workspaceId: string) => {
    if (loadedFor !== workspacePresentationKey()) return;
    const selected = workspaces.find((item) => item.id === workspaceId);
    if (!selected || selected.id === activeWorkspace?.id) return;
    generation.current += 1; requestController.current?.abort(); setRefreshError(null); persistActiveWorkspace(selected.id); setActiveWorkspace(selected); setPending(false); setError(null);
  }, [activeWorkspace?.id, workspaces, loadedFor]);
  const createWorkspace = useCallback(async (input: WorkspaceCreate) => {
    const serial = generation.current; const requestedScope = workspacePresentationKey();
    const created = await workspaceApi.create(input);
    if (serial !== generation.current || requestedScope !== workspacePresentationKey()) throw new DOMException('Workspace context changed', 'AbortError');
    setRefreshError(null);
    persistActiveWorkspace(created.id); setWorkspaces((old) => [...old.filter((item) => item.id !== created.id), created]); setActiveWorkspace(created);
    return created;
  }, []);
  const visible = verified && loadedFor === scope;
  const value = useMemo(() => ({
    workspaces: visible ? workspaces : [], activeWorkspace: visible ? activeWorkspace : null,
    loading: verified && (loadedFor !== scope || (pending && activeWorkspace === null)), error: visible ? error : null,
    refreshing: visible && pending, refreshError: visible ? refreshError : null,
    selectWorkspace, refreshWorkspaces: load, createWorkspace,
  }), [visible, verified, pending, loadedFor, scope, workspaces, activeWorkspace, error, refreshError, selectWorkspace, load, createWorkspace]);
  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}
export function useWorkspace(): WorkspaceContextValue { const value = useContext(WorkspaceContext); if (!value) throw new Error('useWorkspace must be used inside WorkspaceProvider'); return value; }
export function useOptionalWorkspace(): WorkspaceContextValue | null { return useContext(WorkspaceContext); }

type ToastTone = 'success' | 'error' | 'info';
interface ToastItem { id: number; message: string; tone: ToastTone }
interface ToastContextValue { pushToast: (message: string, tone?: ToastTone) => void }
const ToastContext = createContext<ToastContextValue | null>(null);
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const pushToast = useCallback((message: string, tone: ToastTone = 'success') => {
    const next = { id: Date.now() + Math.random(), message, tone }; setItems((current) => [...current, next]);
    window.setTimeout(() => setItems((current) => current.filter((item) => item.id !== next.id)), 3600);
  }, []);
  return <ToastContext.Provider value={{ pushToast }}>{children}<div className="toast-stack" aria-live="polite">
    {items.map((item) => <div key={item.id} className={`toast toast--${item.tone}`}>
      {item.tone === 'success' ? <CheckCircle2 /> : item.tone === 'error' ? <CircleAlert /> : <Info />}
      <span>{item.message}</span><button onClick={() => setItems((current) => current.filter((toast) => toast.id !== item.id))} aria-label="Dismiss"><X /></button>
    </div>)}
  </div></ToastContext.Provider>;
}
export function useToast(): ToastContextValue { const value = useContext(ToastContext); if (!value) throw new Error('useToast must be used inside ToastProvider'); return value; }
