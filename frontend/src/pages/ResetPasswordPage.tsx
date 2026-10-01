import { ArrowLeft, CheckCircle2, Eye, EyeOff, KeyRound, ShieldCheck } from 'lucide-react';
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { Brand } from '@/components/brand';
import { usePublicBranding } from '@/components/public-branding';
import { Button, Field } from '@/components/ui';
import { passwordResetApi } from '@/lib/password-reset-api';
import './PasswordResetPage.css';

function resetToken(search: string, hash: string): string {
  const fragmentToken = new URLSearchParams(hash.replace(/^#/, '')).get('token')?.trim();
  if (fragmentToken) return fragmentToken;
  return new URLSearchParams(search).get('token')?.trim() ?? '';
}

export function ResetPasswordPage() {
  const brand = usePublicBranding();
  const location = useLocation();
  const navigate = useNavigate();
  const tokenRef = useRef(resetToken(location.search, location.hash));
  const token = tokenRef.current;
  const cleaned = useRef(false);
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [success, setSuccess] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!token || cleaned.current) return;
    cleaned.current = true;
    navigate('/reset-password', { replace: true });
  }, [navigate, token]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError('');
    if (!token) { setError('Password reset link is invalid or expired.'); return; }
    if (password.length < 12 || password.length > 256) { setError('Password must be between 12 and 256 characters.'); return; }
    if (password !== confirmPassword) { setError('Passwords do not match.'); return; }
    setSubmitting(true);
    try {
      await passwordResetApi.confirm(token, password, confirmPassword);
      setSuccess(true); setPassword(''); setConfirmPassword('');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Password reset link is invalid or expired.');
    } finally { setSubmitting(false); }
  };

  const authBrand = brand?.authentication;
  return <div className="login-page password-reset-page" style={authBrand?.loginBackground ? { backgroundImage: `url(${authBrand.loginBackground})` } : undefined}>
    <section className="login-panel"><div className="login-panel__inner password-reset-inner">
      <Brand />
      <div className="login-heading"><span className="eyebrow-pill"><KeyRound /> Secure password reset</span><h1>{success ? 'Password updated' : (authBrand?.resetPasswordTitle || 'Choose a new password')}</h1><p>{success ? 'Your password has been changed and older sessions are no longer valid.' : `Use a strong password you have not used for this ${brand?.companyName || 'Northstar'} account.`}</p></div>
      {success ? <div className="password-reset-success" role="status"><span><CheckCircle2 /></span><div><strong>Reset complete</strong><p>Sign in again with your new password on every device.</p></div><Link to="/login"><Button size="lg">Continue to sign in</Button></Link></div> : !token ? <div className="password-reset-invalid" role="alert"><ShieldCheck /><div><strong>This reset link cannot be used.</strong><p>It may be missing, expired, already used, or replaced by a newer request.</p></div><Link to="/forgot-password"><Button variant="secondary">Request a new reset link</Button></Link></div> : <form className="login-form" onSubmit={(event) => void submit(event)} noValidate>
        <Field label="New password" htmlFor="new-password"><div className="password-input"><input id="new-password" type={showPassword ? 'text' : 'password'} value={password} onChange={(event) => setPassword(event.target.value)} minLength={12} maxLength={256} autoComplete="new-password" autoFocus /><button type="button" onClick={() => setShowPassword((value) => !value)} aria-label={showPassword ? 'Hide password' : 'Show password'}>{showPassword ? <EyeOff /> : <Eye />}</button></div></Field>
        <Field label="Confirm new password" htmlFor="confirm-password"><input id="confirm-password" type={showPassword ? 'text' : 'password'} value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} minLength={12} maxLength={256} autoComplete="new-password" /></Field>
        <p className="password-reset-hint">Use at least 12 characters. Your new password must differ from your current password.</p>{error ? <div className="form-error" role="alert">{error}</div> : null}<Button size="lg" type="submit" disabled={submitting}>{submitting ? <span className="button-spinner" /> : 'Reset password'}</Button>
      </form>}
      {!success ? <Link className="password-reset-back text-button" to="/login"><ArrowLeft /> Back to sign in</Link> : null}{authBrand?.footer ? <p className="login-legal">{authBrand.footer}</p> : null}
    </div></section>
    <section className="login-story" aria-label="Password security overview"><div className="login-glow login-glow--one" /><div className="login-glow login-glow--two" /><div className="story-copy"><span className="story-kicker"><span /> Credential security</span><h2>One reset closes the door on old credentials.</h2><p>Reset links are single-use and short-lived, and credential-version checks invalidate access and refresh tokens issued before the reset.</p></div><div className="password-reset-story-card"><ShieldCheck /><div><strong>One-time recovery link</strong><small>Only a hash of the reset secret is stored. Issuing a newer link invalidates previous active links.</small></div></div></section>
  </div>;
}
