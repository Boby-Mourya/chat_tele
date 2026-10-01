import { ArrowLeft, Mail, ShieldCheck } from 'lucide-react';
import { useState, type FormEvent } from 'react';
import { Link } from 'react-router-dom';
import { Brand } from '@/components/brand';
import { usePublicBranding } from '@/components/public-branding';
import { Button, Field } from '@/components/ui';
import { passwordResetApi } from '@/lib/password-reset-api';
import './PasswordResetPage.css';

export function ForgotPasswordPage() {
  const brand = usePublicBranding();
  const [email, setEmail] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState('');

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError('');
    const normalizedEmail = email.trim().toLowerCase();
    if (!/^\S+@\S+\.\S+$/.test(normalizedEmail)) {
      setError('Enter a valid email address.');
      return;
    }
    setSubmitting(true);
    try {
      await passwordResetApi.request(normalizedEmail);
      setSent(true);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Unable to request a password reset email.');
    } finally {
      setSubmitting(false);
    }
  };

  const authBrand = brand?.authentication;
  return <div className="login-page password-reset-page" style={authBrand?.loginBackground ? { backgroundImage: `url(${authBrand.loginBackground})` } : undefined}>
    <section className="login-panel">
      <div className="login-panel__inner password-reset-inner">
        <Brand />
        <div className="login-heading">
          <span className="eyebrow-pill"><ShieldCheck /> Secure account recovery</span>
          <h1>{sent ? 'Check your email' : (authBrand?.forgotPasswordTitle || 'Forgot your password?')}</h1>
          <p>{sent
            ? `If an active ${brand?.companyName || 'Northstar'} account matches that email, we sent a secure password reset link.`
            : 'Enter your work email and we’ll send recovery instructions if the account is eligible.'}</p>
        </div>

        {sent ? <div className="password-reset-success" role="status">
          <span><Mail /></span>
          <div><strong>Recovery request accepted</strong><p>For privacy, this confirmation is the same whether or not an account exists. Reset links expire automatically.</p></div>
          <Button type="button" variant="secondary" onClick={() => setSent(false)}>Request another link</Button>
        </div> : <form className="login-form" onSubmit={(event) => void submit(event)} noValidate>
          <Field label="Work email" htmlFor="reset-email"><input id="reset-email" type="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="you@company.com" autoComplete="email" autoFocus /></Field>
          {error ? <div className="form-error" role="alert">{error}</div> : null}
          <Button size="lg" type="submit" disabled={submitting}>{submitting ? <span className="button-spinner" /> : <>Send reset link <Mail /></>}</Button>
        </form>}
        <Link className="password-reset-back text-button" to="/login"><ArrowLeft /> Back to sign in</Link>
        {authBrand?.footer ? <p className="login-legal">{authBrand.footer}</p> : null}
      </div>
    </section>
    <section className="login-story" aria-label="Password recovery security overview">
      <div className="login-glow login-glow--one" /><div className="login-glow login-glow--two" />
      <div className="story-copy"><span className="story-kicker"><span /> Account recovery</span><h2>Reset securely without exposing who has an account.</h2><p>Recovery requests use generic responses, short-lived one-time links, hashed tokens, and rate limits.</p></div>
      <div className="password-reset-story-card"><ShieldCheck /><div><strong>Existing sessions are invalidated</strong><small>After a successful reset, tokens issued under the old password are rejected and the user must sign in again.</small></div></div>
    </section>
  </div>;
}
