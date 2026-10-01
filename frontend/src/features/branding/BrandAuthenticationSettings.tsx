import { Card, Field } from '@/components/ui';
import type { ExtendedBranding } from '@/features/workspace/settings/workspaceSettings.api';

export function BrandAuthenticationSettings({ value, onChange }: { value: ExtendedBranding; onChange: (value: ExtendedBranding) => void }) {
  const auth = value.authentication;
  const update = (next: Partial<typeof auth>) => onChange({ ...value, authentication: { ...auth, ...next } });
  return <Card className="workspace-panel"><div className="workspace-panel__body">
    <h3>Branded authentication</h3><p>These published values are available before login when an active custom domain resolves to this workspace.</p>
    <div className="two-fields"><Field label="Login logo"><input value={auth.loginLogo} onChange={(event) => update({ loginLogo: event.target.value })} /></Field><Field label="Login background"><input value={auth.loginBackground} onChange={(event) => update({ loginBackground: event.target.value })} /></Field></div>
    <div className="two-fields"><Field label="Login title"><input value={auth.loginTitle} onChange={(event) => update({ loginTitle: event.target.value })} /></Field><Field label="Signup title"><input value={auth.signupTitle} onChange={(event) => update({ signupTitle: event.target.value })} /></Field></div>
    <Field label="Login description"><textarea value={auth.loginDescription} onChange={(event) => update({ loginDescription: event.target.value })} /></Field>
    <div className="two-fields"><Field label="Forgot-password title"><input value={auth.forgotPasswordTitle} onChange={(event) => update({ forgotPasswordTitle: event.target.value })} /></Field><Field label="Reset-password title"><input value={auth.resetPasswordTitle} onChange={(event) => update({ resetPasswordTitle: event.target.value })} /></Field></div>
    <div className="two-fields"><Field label="MFA title"><input value={auth.mfaTitle} onChange={(event) => update({ mfaTitle: event.target.value })} /></Field><Field label="Invitation title"><input value={auth.invitationTitle} onChange={(event) => update({ invitationTitle: event.target.value })} /></Field></div>
    <div className="two-fields"><Field label="Terms URL"><input value={auth.termsUrl} onChange={(event) => update({ termsUrl: event.target.value })} /></Field><Field label="Privacy URL"><input value={auth.privacyUrl} onChange={(event) => update({ privacyUrl: event.target.value })} /></Field></div>
    <Field label="Support URL"><input value={auth.supportUrl} onChange={(event) => update({ supportUrl: event.target.value })} /></Field>
    <Field label="Authentication footer"><textarea value={auth.footer} onChange={(event) => update({ footer: event.target.value })} /></Field>
  </div></Card>;
}
