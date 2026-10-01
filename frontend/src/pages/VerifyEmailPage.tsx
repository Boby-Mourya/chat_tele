import { ArrowRight, CheckCircle2, MailCheck, RefreshCw, ShieldCheck } from 'lucide-react';
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom';
import { Brand } from '@/components/brand';
import { useAuth } from '@/components/providers';
import { Button, Field } from '@/components/ui';
import { emailVerificationApi } from '@/lib/email-verification-api';
import './VerifyEmailPage.css';

type VerificationState = 'waiting' | 'checking' | 'success' | 'error';

function verificationToken(search: string, hash: string): string {
  const fragmentToken = new URLSearchParams(hash.replace(/^#/, '')).get('token')?.trim();
  if (fragmentToken) return fragmentToken;
  // Query support preserves links generated before the fragment-token hardening.
  return new URLSearchParams(search).get('token')?.trim() ?? '';
}

export function VerifyEmailPage() {
  const { session, logout } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const token = verificationToken(location.search, location.hash);
  const startedVerification = useRef(false);
  const [state, setState] = useState<VerificationState>(token ? 'checking' : 'waiting');
  const [email, setEmail] = useState(session?.user.email ?? '');
  const [message, setMessage] = useState('');
  const [resending, setResending] = useState(false);
  const [cooldown, setCooldown] = useState(0);

  useEffect(() => {
    if (!token || startedVerification.current) return;
    startedVerification.current = true;
    // Remove bearer-style verification material from browser history/address bar
    // before calling the API. Fragment links never reached the web server, while
    // this also cleans up legacy query-string links immediately after hydration.
    navigate('/verify-email', { replace: true });
    const run = async () => {
      setState('checking');
      setMessage('Checking your verification link…');
      try {
        await emailVerificationApi.verify(token);
        if (session) {
          try {
            const refreshed = await emailVerificationApi.refreshSession();
            if (refreshed.user.emailVerified !== false) {
              navigate('/', { replace: true });
              return;
            }
          } catch {
            // The email is verified even if this browser no longer owns a valid session.
          }
        }
        setState('success');
        setMessage('Your email address is verified. Sign in to continue.');
      } catch (reason) {
        setState('error');
        setMessage(reason instanceof Error ? reason.message : 'Verification link is invalid or expired.');
      }
    };
    void run();
  }, [navigate, session, token]);

  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = window.setInterval(() => {
      setCooldown((value) => Math.max(0, value - 1));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [cooldown]);

  if (session?.user.emailVerified !== false && !token) return <Navigate to="/" replace />;

  const resend = async (event: FormEvent) => {
    event.preventDefault();
    setMessage('');
    const normalizedEmail = email.trim().toLowerCase();
    if (!/^\S+@\S+\.\S+$/.test(normalizedEmail)) {
      setState('error');
      setMessage('Enter a valid email address.');
      return;
    }
    setResending(true);
    try {
      await emailVerificationApi.resend(normalizedEmail);
      setState('waiting');
      setCooldown(60);
      setMessage('If that account needs verification, a new email is on the way.');
    } catch (reason) {
      setState('error');
      setMessage(reason instanceof Error ? reason.message : 'Unable to request a verification email.');
    } finally {
      setResending(false);
    }
  };

  const switchAccount = async () => {
    if (session) await logout();
    navigate('/login', { replace: true });
  };

  return <div className="login-page verify-email-page">
    <section className="login-panel verify-email-panel">
      <div className="login-panel__inner verify-email-inner">
        <Brand />
        <div className="login-heading verify-email-heading">
          <span className="eyebrow-pill"><MailCheck /> Secure account activation</span>
          <h1>{state === 'success' ? 'Email verified' : state === 'checking' ? 'Verifying your email' : 'Check your email'}</h1>
          <p>{state === 'success'
            ? 'Your Northstar account can now access its workspace.'
            : 'Verify your business email before entering your workspace.'}</p>
        </div>

        {state === 'checking' ? <div className="verification-status verification-status--checking" role="status">
          <span className="button-spinner verification-spinner" />
          <div><strong>Verifying secure link</strong><small>{message}</small></div>
        </div> : null}

        {state === 'success' ? <div className="verification-success">
          <span><CheckCircle2 /></span>
          <div><strong>Verification complete</strong><p>{message}</p></div>
          <Link to="/login"><Button size="lg">Continue to sign in <ArrowRight /></Button></Link>
        </div> : null}

        {state !== 'checking' && state !== 'success' ? <>
          <div className="verification-card">
            <span className="verification-card__icon"><MailCheck /></span>
            <div>
              <strong>Verification email sent</strong>
              <p>Open the email we sent to <b>{session?.user.email ?? 'your business email'}</b> and select the verification link. Links expire for security.</p>
            </div>
          </div>

          <form className="login-form verify-email-form" onSubmit={(event) => void resend(event)} noValidate>
            {!session ? <Field label="Business email" htmlFor="verification-email">
              <input id="verification-email" type="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="you@company.com" autoComplete="email" />
            </Field> : null}
            {message ? <div className={state === 'error' ? 'form-error' : 'verification-message'} role={state === 'error' ? 'alert' : 'status'}>{message}</div> : null}
            <Button size="lg" type="submit" disabled={resending || cooldown > 0} variant="secondary">
              {resending ? <span className="button-spinner verification-spinner verification-spinner--dark" /> : <RefreshCw />}
              {cooldown > 0 ? `Resend available in ${cooldown}s` : 'Resend verification email'}
            </Button>
          </form>
          <div className="verify-email-actions">
            {session ? <button className="text-button" type="button" onClick={() => void switchAccount()}>Use a different account</button> : <Link className="text-button" to="/login">Back to sign in</Link>}
          </div>
        </> : null}
      </div>
    </section>
    <section className="login-story" aria-label="Email verification security overview">
      <div className="login-glow login-glow--one" /><div className="login-glow login-glow--two" />
      <div className="story-copy"><span className="story-kicker"><span /> Account security</span><h2>Verify ownership before workspace access begins.</h2><p>Verification links are random, stored only as hashes, expire automatically, and cannot activate an account more than once.</p></div>
      <div className="verification-story-card"><ShieldCheck /><div><strong>Workspace access stays locked</strong><small>Unverified self-service accounts can authenticate only far enough to verify, resend, refresh, or sign out.</small></div></div>
    </section>
  </div>;
}
