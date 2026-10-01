import { ArrowRight, Building2, Eye, EyeOff, Layers3, ShieldCheck, Sparkles, UserPlus } from 'lucide-react';
import { useState, type FormEvent } from 'react';
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom';
import { Brand } from '@/components/brand';
import { usePublicBranding } from '@/components/public-branding';
import { useAuth } from '@/components/providers';
import { Button, Field } from '@/components/ui';
import './SignupPage.css';

export function SignupPage() {
  const { session, signup } = useAuth();
  const publicBrand = usePublicBranding();
  const navigate = useNavigate();
  const location = useLocation();
  const invitationToken = new URLSearchParams(location.hash.replace(/^#/, '')).get('invite')?.trim() ?? '';
  const invited = invitationToken.length > 0;
  const [name, setName] = useState('');
  const [organizationName, setOrganizationName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [termsAccepted, setTermsAccepted] = useState(false);
  const [privacyAccepted, setPrivacyAccepted] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  if (session) return <Navigate to={session.user.emailVerified === false ? '/verify-email' : '/'} replace />;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError('');
    const normalizedName = name.trim().replace(/\s+/g, ' ');
    const normalizedOrganization = organizationName.trim().replace(/\s+/g, ' ');
    const normalizedEmail = email.trim().toLowerCase();
    if (normalizedName.length < 2) { setError('Enter your full name.'); return; }
    if (!invited && normalizedOrganization.length < 2) { setError('Enter your company or organization name.'); return; }
    if (!/^\S+@\S+\.\S+$/.test(normalizedEmail)) { setError('Enter a valid business email address.'); return; }
    if (password.length < 12) { setError('Password must be at least 12 characters.'); return; }
    if (!termsAccepted || !privacyAccepted) {
      setError('Accept the Terms and Privacy Policy to create your account.');
      return;
    }

    setSubmitting(true);
    try {
      const created = await signup({
        name: normalizedName,
        ...(invited ? { workspaceInvitationToken: invitationToken } : { organizationName: normalizedOrganization }),
        email: normalizedEmail,
        password,
        termsAccepted: true,
        privacyAccepted: true,
      });
      navigate(created.user.emailVerified === false ? '/verify-email' : '/', { replace: true });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'We could not create your account.');
    } finally {
      setSubmitting(false);
    }
  };

  const authBrand = publicBrand?.authentication;
  const termsUrl = authBrand?.termsUrl || '#terms';
  const privacyUrl = authBrand?.privacyUrl || '#privacy';
  const signupTitle = invited ? (authBrand?.invitationTitle || 'Join your workspace') : (authBrand?.signupTitle || 'Create your account');

  return <div className="login-page signup-page" style={authBrand?.loginBackground ? { backgroundImage: `url(${authBrand.loginBackground})` } : undefined}>
    <section className="login-panel signup-panel">
      <div className="login-panel__inner signup-panel__inner">
        <Brand />
        <div className="login-heading signup-heading">
          <span className="eyebrow-pill"><UserPlus /> {invited ? 'Workspace invitation' : 'Start your workspace'}</span>
          <h1>{signupTitle}</h1>
          <p>{invited ? 'Create your account to accept the workspace invitation.' : (authBrand?.loginDescription || `Set up your ${publicBrand?.companyName || 'Northstar'} workspace and become its first owner.`)}</p>
        </div>
        <form className="login-form signup-form" onSubmit={(event) => void submit(event)} noValidate>
          <div className={invited ? '' : 'signup-grid'}>
            <Field label="Your name" htmlFor="signup-name">
              <input id="signup-name" value={name} onChange={(event) => setName(event.target.value)} placeholder="Sakshee Jha" autoComplete="name" autoFocus />
            </Field>
            {!invited ? <Field label="Organization" htmlFor="signup-organization">
              <input id="signup-organization" value={organizationName} onChange={(event) => setOrganizationName(event.target.value)} placeholder="NorthStar Academy" autoComplete="organization" />
            </Field> : null}
          </div>
          <Field label="Business email" htmlFor="signup-email">
            <input id="signup-email" type="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="you@company.com" autoComplete="email" />
          </Field>
          <Field label="Password" htmlFor="signup-password">
            <div className="password-input">
              <input id="signup-password" type={showPassword ? 'text' : 'password'} value={password} onChange={(event) => setPassword(event.target.value)} placeholder="At least 12 characters" autoComplete="new-password" />
              <button type="button" onClick={() => setShowPassword((value) => !value)} aria-label={showPassword ? 'Hide password' : 'Show password'}>{showPassword ? <EyeOff /> : <Eye />}</button>
            </div>
            <small>Use at least 12 characters. Your password is securely hashed before storage.</small>
          </Field>
          <div className="signup-consents">
            <label><input type="checkbox" checked={termsAccepted} onChange={(event) => setTermsAccepted(event.target.checked)} /> <span>I agree to the <a href={termsUrl}>Terms of Service</a>.</span></label>
            <label><input type="checkbox" checked={privacyAccepted} onChange={(event) => setPrivacyAccepted(event.target.checked)} /> <span>I agree to the <a href={privacyUrl}>Privacy Policy</a>.</span></label>
          </div>
          {error ? <div className="form-error" role="alert">{error}</div> : null}
          <Button size="lg" type="submit" disabled={submitting}>{submitting ? <span className="button-spinner" /> : <>{invited ? 'Join workspace' : 'Create account'} <ArrowRight /></>}</Button>
        </form>
        <p className="signup-copy">Already have an account? <Link className="text-button" to="/login">Sign in</Link></p>
        <p className="login-legal signup-legal">{authBrand?.footer || (invited ? 'Your access is limited to the role assigned by the workspace administrator.' : 'You’ll be the owner of this organization and its first workspace.')}</p>
      </div>
    </section>
    <section className="login-story" aria-label="Account setup overview">
      <div className="login-glow login-glow--one" /><div className="login-glow login-glow--two" />
      <div className="story-copy"><span className="story-kicker"><span /> One account, multiple workspaces</span><h2>{invited ? 'Join an existing workspace without changing its current configuration.' : 'Start with a secure workspace built for your AI operations.'}</h2><p>{invited ? 'Your invitation connects this account to the existing tenant and workspace using the role selected by its administrator.' : 'Your first account becomes the Tenant Owner and Workspace Admin, ready for agents, channels, conversations, Education and CRM workflows.'}</p></div>
      <div className="signup-story-card">
        <span><Building2 /></span><div><strong>{invited ? 'Existing workspace preserved' : 'Organization provisioned'}</strong><small>{invited ? 'No agents, knowledge, channels, or settings are replaced.' : 'Your Tenant and default Workspace are created together.'}</small></div>
        <span><ShieldCheck /></span><div><strong>{invited ? 'Assigned permissions' : 'Owner permissions'}</strong><small>{invited ? 'Your account receives only the workspace role chosen for the invitation.' : 'You receive Tenant Owner and Workspace Admin access.'}</small></div>
        <span><Layers3 /></span><div><strong>Existing architecture preserved</strong><small>Signup connects directly to the current workspace and RBAC system.</small></div>
      </div>
      <div className="story-features"><span><Sparkles /> Ready for agents</span><span><Layers3 /> Workspace scoped</span><span><ShieldCheck /> Secure by default</span></div>
    </section>
  </div>;
}
