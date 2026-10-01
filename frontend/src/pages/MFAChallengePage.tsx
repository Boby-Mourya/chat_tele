import { ArrowLeft, KeyRound, ShieldCheck } from 'lucide-react';
import { useState, type FormEvent } from 'react';
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom';
import { Brand } from '@/components/brand';
import { usePublicBranding } from '@/components/public-branding';
import { useAuth } from '@/components/providers';
import { Button, Field } from '@/components/ui';

interface ChallengeLocationState { challengeToken?: string; from?: string }

export function MFAChallengePage() {
  const { session, completeMFA } = useAuth();
  const brand = usePublicBranding();
  const location = useLocation();
  const navigate = useNavigate();
  const state = (location.state as ChallengeLocationState | null) ?? null;
  const challengeToken = state?.challengeToken ?? '';
  const target = state?.from ?? '/';
  const [mode, setMode] = useState<'totp' | 'recovery'>('totp');
  const [code, setCode] = useState('');
  const [recoveryCode, setRecoveryCode] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  if (session) return <Navigate to={session.user.emailVerified === false ? '/verify-email' : target} replace />;

  async function submit(event: FormEvent) {
    event.preventDefault(); setError('');
    if (!challengeToken) { setError('Your sign-in challenge is missing or expired. Sign in again.'); return; }
    if (mode === 'totp' && !/^\d{6}$/.test(code)) { setError('Enter the 6-digit code from your authenticator app.'); return; }
    if (mode === 'recovery' && recoveryCode.replace(/[^a-z0-9]/gi, '').length < 8) { setError('Enter one of your recovery codes.'); return; }
    setSubmitting(true);
    try {
      const next = await completeMFA(challengeToken, mode === 'totp' ? { code } : { recoveryCode: recoveryCode.trim() });
      navigate(next.user.emailVerified === false ? '/verify-email' : target, { replace: true });
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'We could not verify your second factor.'); }
    finally { setSubmitting(false); }
  }

  const authBrand = brand?.authentication;
  return <div className="login-page" style={authBrand?.loginBackground ? { backgroundImage: `url(${authBrand.loginBackground})` } : undefined}>
    <section className="login-panel"><div className="login-panel__inner">
      <Brand />
      <div className="login-heading"><span className="eyebrow-pill"><ShieldCheck /> Secure sign in</span><h1>{authBrand?.mfaTitle || 'Verify it’s you'}</h1><p>Complete multi-factor authentication before {brand?.companyName || 'Northstar'} creates your session.</p></div>
      {!challengeToken ? <div className="form-error" role="alert">Your sign-in challenge is missing or expired. Sign in again.</div> : null}
      <form className="login-form" onSubmit={(event) => void submit(event)} noValidate>
        {mode === 'totp' ? <Field label="Authenticator code" htmlFor="mfa-code"><input id="mfa-code" inputMode="numeric" autoComplete="one-time-code" value={code} onChange={(event) => setCode(event.target.value.replace(/\D/g, '').slice(0, 6))} placeholder="000000" autoFocus /></Field> : <Field label="Recovery code" htmlFor="mfa-recovery"><input id="mfa-recovery" autoComplete="off" value={recoveryCode} onChange={(event) => setRecoveryCode(event.target.value.toUpperCase())} placeholder="ABCD-EFGH-JKLM" autoFocus /></Field>}
        {error ? <div className="form-error" role="alert">{error}</div> : null}<Button size="lg" type="submit" disabled={submitting || !challengeToken}>{submitting ? <span className="button-spinner" /> : <>Verify and sign in <KeyRound /></>}</Button>
      </form>
      <button type="button" className="text-button" onClick={() => { setMode((value) => value === 'totp' ? 'recovery' : 'totp'); setError(''); }}>{mode === 'totp' ? 'Use a recovery code instead' : 'Use authenticator code instead'}</button>
      <p className="signup-copy"><Link className="text-button" to="/login"><ArrowLeft /> Back to sign in</Link></p>{authBrand?.footer ? <p className="login-legal">{authBrand.footer}</p> : null}
    </div></section>
    <section className="login-story" aria-label="Multi-factor authentication"><div className="login-glow login-glow--one" /><div className="login-glow login-glow--two" /><div className="story-copy"><span className="story-kicker"><span /> Account protection</span><h2>Your password is only the first step.</h2><p>{brand?.companyName || 'Northstar'} requires your authenticator or a one-time recovery code before issuing an authenticated workspace session.</p></div></section>
  </div>;
}
