import {
  ArrowRight,
  Building2,
  CheckCircle2,
  Clock3,
  LogIn,
  ShieldCheck,
  UserPlus,
  UsersRound,
  XCircle,
} from 'lucide-react';
import { useEffect, useState, type FormEvent, type ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import { Brand } from '@/components/brand';
import { useAuth } from '@/components/providers';
import { Badge, Button, Field } from '@/components/ui';
import {
  activateWorkspaceInvitationSession,
  workspaceInvitationApi,
  type WorkspaceInvitationPreview,
} from '@/lib/workspace-team-api';
import '@/pages/WorkspaceTeam.css';

const PENDING_INVITATION_KEY = 'northstar.pending-workspace-invitation';

function captureInvitationToken(): string {
  const fragment = new URLSearchParams(window.location.hash.replace(/^#/, ''));
  const supplied = fragment.get('token')?.trim() ?? '';
  if (supplied) sessionStorage.setItem(PENDING_INVITATION_KEY, supplied);
  if (window.location.hash) {
    window.history.replaceState(null, document.title, `${window.location.pathname}${window.location.search}`);
  }
  return supplied || sessionStorage.getItem(PENDING_INVITATION_KEY) || '';
}

function clearInvitationToken(): void {
  sessionStorage.removeItem(PENDING_INVITATION_KEY);
}

function roleLabel(role: WorkspaceInvitationPreview['role']): string {
  const labels: Record<WorkspaceInvitationPreview['role'], string> = {
    workspace_admin: 'Workspace admin',
    manager: 'Manager',
    operator: 'Operator',
    analyst: 'Analyst',
    viewer: 'Viewer',
  };
  return labels[role];
}

export function WorkspaceInvitationPage() {
  const { session, logout } = useAuth();
  const navigate = useNavigate();
  const [token] = useState(captureInvitationToken);
  const [preview, setPreview] = useState<WorkspaceInvitationPreview | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [declined, setDeclined] = useState(false);
  const [name, setName] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [termsAccepted, setTermsAccepted] = useState(false);
  const [privacyAccepted, setPrivacyAccepted] = useState(false);

  useEffect(() => {
    let active = true;
    if (!token) {
      setError('This invitation link is missing its secure token. Ask the workspace administrator to resend it.');
      setLoading(false);
      return () => { active = false; };
    }
    void workspaceInvitationApi.preview(token)
      .then((value) => { if (active) setPreview(value); })
      .catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : 'This invitation is unavailable.');
      })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [token]);

  async function complete(value: Awaited<ReturnType<typeof workspaceInvitationApi.accept>>) {
    activateWorkspaceInvitationSession(value);
    clearInvitationToken();
    navigate('/', { replace: true });
  }

  async function acceptExistingAccount() {
    if (!preview) return;
    setSubmitting(true);
    setError('');
    try {
      await complete(await workspaceInvitationApi.accept(token));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'The invitation could not be accepted.');
    } finally {
      setSubmitting(false);
    }
  }

  async function createInvitedAccount(event: FormEvent) {
    event.preventDefault();
    setError('');
    const normalizedName = name.trim().replace(/\s+/g, ' ');
    if (normalizedName.length < 2) {
      setError('Enter your full name.');
      return;
    }
    if (password.length < 12) {
      setError('Password must contain at least 12 characters.');
      return;
    }
    if (password !== confirmPassword) {
      setError('Passwords do not match.');
      return;
    }
    if (!termsAccepted || !privacyAccepted) {
      setError('Accept the Terms of Service and Privacy Policy to join the workspace.');
      return;
    }
    setSubmitting(true);
    try {
      await complete(await workspaceInvitationApi.signup({
        token,
        name: normalizedName,
        password,
        termsAccepted: true,
        privacyAccepted: true,
      }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Your invited account could not be created.');
    } finally {
      setSubmitting(false);
    }
  }

  async function decline() {
    setSubmitting(true);
    setError('');
    try {
      await workspaceInvitationApi.decline(token);
      clearInvitationToken();
      setDeclined(true);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'The invitation could not be declined.');
    } finally {
      setSubmitting(false);
    }
  }

  async function switchAccount() {
    setSubmitting(true);
    try {
      await logout();
      navigate('/login', { replace: true, state: { from: '/workspace-invitation' } });
    } finally {
      setSubmitting(false);
    }
  }

  if (declined) {
    return <InvitationShell>
      <div className="workspace-invitation__result">
        <span className="workspace-invitation__result-icon workspace-invitation__result-icon--muted"><XCircle /></span>
        <h1>Invitation declined</h1>
        <p>You have not been added to the workspace. A workspace administrator can send a new invitation later.</p>
        <Button variant="secondary" onClick={() => navigate('/login', { replace: true })}>Return to sign in</Button>
      </div>
    </InvitationShell>;
  }

  if (loading) {
    return <InvitationShell>
      <div className="workspace-invitation__result" aria-live="polite">
        <span className="workspace-invitation__spinner" aria-hidden="true" />
        <h1>Checking your invitation</h1>
        <p>We are verifying the secure, one-time workspace link.</p>
      </div>
    </InvitationShell>;
  }

  if (!preview) {
    return <InvitationShell>
      <div className="workspace-invitation__result">
        <span className="workspace-invitation__result-icon workspace-invitation__result-icon--danger"><XCircle /></span>
        <h1>Invitation unavailable</h1>
        <p>{error || 'This invitation is invalid, expired, declined, or revoked.'}</p>
        <Button variant="secondary" onClick={() => navigate('/login', { replace: true })}>Return to sign in</Button>
      </div>
    </InvitationShell>;
  }

  const matchingSession = session?.user.email.toLowerCase() === preview.email.toLowerCase()
    ? session
    : null;
  const differentSession = session && !matchingSession ? session : null;
  const expiresAt = new Date(preview.expiresAt);

  return <InvitationShell>
    <div className="workspace-invitation__heading">
      <span className="eyebrow-pill"><UserPlus /> Secure workspace invitation</span>
      <h1>Join {preview.workspaceName}</h1>
      <p>{preview.tenantName} invited <strong>{preview.email}</strong> to collaborate in this workspace.</p>
    </div>

    <div className="workspace-invitation__summary" aria-label="Invitation details">
      <span><Building2 /></span>
      <div><small>Workspace</small><strong>{preview.workspaceName}</strong><p>{preview.tenantName}</p></div>
      <Badge tone="purple">{roleLabel(preview.role)}</Badge>
    </div>
    <div className="workspace-invitation__facts">
      <span><ShieldCheck /><span><small>Agent access</small><strong>{preview.allAgentsAccess ? 'All workspace agents' : `${preview.agentCount} selected agent${preview.agentCount === 1 ? '' : 's'}`}</strong></span></span>
      <span><Clock3 /><span><small>Invitation expires</small><strong>{Number.isNaN(expiresAt.getTime()) ? preview.expiresAt : expiresAt.toLocaleString()}</strong></span></span>
    </div>

    {differentSession ? <div className="workspace-invitation__action">
      <div className="workspace-invitation__account-warning" role="alert">
        <ShieldCheck /><span><strong>Use the invited account</strong><small>You are signed in as {differentSession.user.email}, but this invitation belongs to {preview.email}.</small></span>
      </div>
      {error ? <div className="form-error" role="alert">{error}</div> : null}
      <Button size="lg" variant="secondary" disabled={submitting} onClick={() => void switchAccount()}>
        Sign out and switch account
      </Button>
    </div> : preview.existingUser ? <div className="workspace-invitation__action">
      {matchingSession ? matchingSession.user.emailVerified === false ? <>
        <div className="workspace-invitation__account-warning" role="alert">
          <ShieldCheck /><span><strong>Verify your email first</strong><small>This existing account must complete email verification before it can accept workspace access.</small></span>
        </div>
        <Button size="lg" onClick={() => navigate('/verify-email', { state: { from: '/workspace-invitation' } })}>
          Verify email to continue <ArrowRight />
        </Button>
      </> : <>
        <div className="workspace-invitation__signed-in"><CheckCircle2 /><span><small>Signed in as</small><strong>{matchingSession.user.email}</strong></span></div>
        {error ? <div className="form-error" role="alert">{error}</div> : null}
        <Button size="lg" disabled={submitting} onClick={() => void acceptExistingAccount()}>
          {submitting ? <span className="button-spinner" /> : <>Accept and open workspace <ArrowRight /></>}
        </Button>
      </> : <>
        <p className="workspace-invitation__instruction">An account already exists for this email. Sign in first, then return here to accept the invitation.</p>
        <Button size="lg" onClick={() => navigate('/login', { state: { from: '/workspace-invitation' } })}>
          <LogIn /> Sign in to accept
        </Button>
      </>}
    </div> : <form className="workspace-invitation__form" onSubmit={(event) => void createInvitedAccount(event)} noValidate>
      <h2>Create your invited account</h2>
      <p>Your email was verified through this one-time invitation. Choose your name and password to join.</p>
      <Field label="Invited email" htmlFor="invited-email"><input id="invited-email" value={preview.email} readOnly /></Field>
      <Field label="Full name" htmlFor="invited-name"><input id="invited-name" value={name} onChange={(event) => setName(event.target.value)} autoComplete="name" autoFocus /></Field>
      <Field label="Password" htmlFor="invited-password" hint="Use at least 12 characters."><input id="invited-password" type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="new-password" /></Field>
      <Field label="Confirm password" htmlFor="invited-password-confirm"><input id="invited-password-confirm" type="password" value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} autoComplete="new-password" /></Field>
      <label className="workspace-invitation__consent"><input type="checkbox" checked={termsAccepted} onChange={(event) => setTermsAccepted(event.target.checked)} /><span>I accept the <a href="/terms" target="_blank" rel="noreferrer">Terms of Service</a>.</span></label>
      <label className="workspace-invitation__consent"><input type="checkbox" checked={privacyAccepted} onChange={(event) => setPrivacyAccepted(event.target.checked)} /><span>I accept the <a href="/privacy" target="_blank" rel="noreferrer">Privacy Policy</a>.</span></label>
      {error ? <div className="form-error" role="alert">{error}</div> : null}
      <Button size="lg" type="submit" disabled={submitting}>
        {submitting ? <span className="button-spinner" /> : <>Create account and join <ArrowRight /></>}
      </Button>
    </form>}

    <div className="workspace-invitation__decline">
      <button type="button" disabled={submitting} onClick={() => void decline()}>Decline invitation</button>
      <small>Declining invalidates this one-time link.</small>
    </div>
  </InvitationShell>;
}

function InvitationShell({ children }: { children: ReactNode }) {
  return <main className="workspace-invitation-page">
    <section className="workspace-invitation-card">
      <Brand />
      {children}
    </section>
    <aside className="workspace-invitation-story" aria-label="Workspace collaboration">
      <div className="workspace-invitation-story__glow" />
      <span className="story-kicker"><span /> Private by design</span>
      <h2>Collaborate with the exact access your team assigned.</h2>
      <p>Every invitation is one-time, expires automatically, and applies only to the selected tenant, workspace, role, and agents.</p>
      <div className="workspace-invitation-story__features">
        <span><ShieldCheck /> Hashed invitation tokens</span>
        <span><UsersRound /> Workspace-scoped membership</span>
        <span><Building2 /> Role and agent restrictions</span>
      </div>
    </aside>
  </main>;
}
