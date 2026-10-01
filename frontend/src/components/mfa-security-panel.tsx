import { CheckCircle2, Copy, KeyRound, RefreshCw, ShieldCheck, ShieldOff } from 'lucide-react';
import { useEffect, useState, type FormEvent } from 'react';
import { useToast } from '@/components/providers';
import { Badge, Button, Field } from '@/components/ui';
import { mfaApi, type MFAProtectedAction, type MFASetupMaterial, type MFAStatus } from '@/lib/mfa-api';
import { createQrAssets } from '@/lib/qr';
import './mfa-security-panel.css';

export function MFASecurityPanel() {
  const { pushToast } = useToast();
  const [status, setStatus] = useState<MFAStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [setup, setSetup] = useState<MFASetupMaterial | null>(null);
  const [qrDataUrl, setQrDataUrl] = useState('');
  const [currentPassword, setCurrentPassword] = useState('');
  const [confirmCode, setConfirmCode] = useState('');
  const [savedRecoveryCodes, setSavedRecoveryCodes] = useState(false);
  const [actionPassword, setActionPassword] = useState('');
  const [actionFactor, setActionFactor] = useState('');
  const [useRecovery, setUseRecovery] = useState(false);
  const [newRecoveryCodes, setNewRecoveryCodes] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function refreshStatus() {
    setLoading(true);
    try { setStatus(await mfaApi.status()); }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'MFA status could not be loaded.'); }
    finally { setLoading(false); }
  }

  useEffect(() => { void refreshStatus(); }, []);
  useEffect(() => {
    let active = true;
    if (!setup?.otpauthUri) { setQrDataUrl(''); return () => { active = false; }; }
    void createQrAssets(setup.otpauthUri).then((assets) => { if (active) setQrDataUrl(assets.pngDataUrl); });
    return () => { active = false; };
  }, [setup?.otpauthUri]);

  async function beginSetup(event: FormEvent) {
    event.preventDefault(); setError(''); setBusy(true);
    try {
      const material = await mfaApi.setup(currentPassword);
      setSetup(material); setCurrentPassword(''); setSavedRecoveryCodes(false);
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'MFA setup could not be started.'); }
    finally { setBusy(false); }
  }

  async function confirm(event: FormEvent) {
    event.preventDefault(); setError('');
    if (!savedRecoveryCodes) { setError('Save your recovery codes before enabling MFA.'); return; }
    if (!/^\d{6}$/.test(confirmCode)) { setError('Enter the 6-digit code from your authenticator app.'); return; }
    setBusy(true);
    try {
      await mfaApi.confirm(confirmCode);
      setSetup(null); setConfirmCode(''); setSavedRecoveryCodes(false);
      await refreshStatus(); pushToast('Multi-factor authentication enabled');
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'MFA could not be enabled.'); }
    finally { setBusy(false); }
  }

  function protectedInput(): MFAProtectedAction | null {
    if (!actionPassword) { setError('Enter your current password.'); return null; }
    if (useRecovery) {
      if (actionFactor.replace(/[^a-z0-9]/gi, '').length < 8) { setError('Enter a valid recovery code.'); return null; }
      return { currentPassword: actionPassword, recoveryCode: actionFactor.trim() };
    }
    if (!/^\d{6}$/.test(actionFactor)) { setError('Enter the 6-digit code from your authenticator app.'); return null; }
    return { currentPassword: actionPassword, code: actionFactor };
  }

  async function regenerate() {
    setError(''); const input = protectedInput(); if (!input) return; setBusy(true);
    try {
      const result = await mfaApi.regenerateRecoveryCodes(input);
      setNewRecoveryCodes(result.recoveryCodes); setActionFactor(''); setActionPassword('');
      await refreshStatus(); pushToast('Recovery codes regenerated');
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Recovery codes could not be regenerated.'); }
    finally { setBusy(false); }
  }

  async function disable() {
    setError(''); const input = protectedInput(); if (!input) return; setBusy(true);
    try {
      await mfaApi.disable(input);
      setNewRecoveryCodes([]); setActionFactor(''); setActionPassword(''); setUseRecovery(false);
      await refreshStatus(); pushToast('Multi-factor authentication disabled', 'info');
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'MFA could not be disabled.'); }
    finally { setBusy(false); }
  }

  if (loading && !status) return <div className="mfa-security"><span className="button-spinner" /> Loading multi-factor authentication…</div>;

  return <section className="mfa-security" aria-labelledby="mfa-security-title">
    <div className="mfa-security__heading">
      <div><span className="mfa-security__icon"><ShieldCheck /></span><span><strong id="mfa-security-title">Your multi-factor authentication</strong><small>Protect your Northstar account with a time-based authenticator and one-time recovery codes.</small></span></div>
      <Badge tone={status?.enabled ? 'success' : 'neutral'}>{status?.enabled ? 'Enabled' : 'Not enabled'}</Badge>
    </div>

    {error ? <div className="form-error" role="alert">{error}</div> : null}

    {!status?.enabled && !setup ? <form className="mfa-security__form" onSubmit={(event) => void beginSetup(event)}>
      <Field label="Current password" htmlFor="mfa-current-password"><input id="mfa-current-password" type="password" autoComplete="current-password" value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} /></Field>
      <Button type="submit" icon={KeyRound} disabled={busy || !currentPassword}>{busy ? 'Starting…' : 'Set up authenticator'}</Button>
    </form> : null}

    {setup ? <div className="mfa-setup-flow">
      <div className="mfa-setup-flow__step"><strong>1. Add Northstar to your authenticator app</strong><p>Scan this QR code, or enter the setup key manually.</p><div className="mfa-setup-flow__qr">{qrDataUrl ? <img src={qrDataUrl} alt="Authenticator setup QR code" /> : <span className="button-spinner" />}</div><div className="mfa-secret-row"><code>{setup.secret}</code><button type="button" className="icon-button" aria-label="Copy authenticator setup key" onClick={() => void navigator.clipboard.writeText(setup.secret).then(() => pushToast('Setup key copied'))}><Copy /></button></div></div>
      <div className="mfa-setup-flow__step"><strong>2. Save your recovery codes</strong><p>Each code works once. Store them somewhere safe outside this browser.</p><RecoveryCodes codes={setup.recoveryCodes} onCopy={() => pushToast('Recovery codes copied')} /><label className="mfa-recovery-check"><input type="checkbox" checked={savedRecoveryCodes} onChange={(event) => setSavedRecoveryCodes(event.target.checked)} /> I saved these recovery codes securely.</label></div>
      <form className="mfa-setup-flow__step" onSubmit={(event) => void confirm(event)}><strong>3. Confirm your authenticator</strong><Field label="6-digit code" htmlFor="mfa-confirm-code"><input id="mfa-confirm-code" inputMode="numeric" autoComplete="one-time-code" value={confirmCode} onChange={(event) => setConfirmCode(event.target.value.replace(/\D/g, '').slice(0, 6))} placeholder="000000" /></Field><Button type="submit" disabled={busy}>{busy ? 'Enabling…' : 'Enable MFA'}</Button></form>
    </div> : null}

    {status?.enabled ? <div className="mfa-enabled-controls">
      <div className="mfa-enabled-summary"><CheckCircle2 /><span><strong>Authenticator protection is active</strong><small>{status.confirmedAt ? `Enabled ${new Date(status.confirmedAt).toLocaleString()}. ` : ''}{status.unusedRecoveryCodes} recovery codes remain.</small></span></div>
      {newRecoveryCodes.length ? <div className="mfa-new-recovery"><strong>New recovery codes</strong><p>The previous set is no longer valid. Copy this new set now.</p><RecoveryCodes codes={newRecoveryCodes} onCopy={() => pushToast('Recovery codes copied')} /></div> : null}
      <div className="mfa-security__form"><Field label="Current password" htmlFor="mfa-action-password"><input id="mfa-action-password" type="password" autoComplete="current-password" value={actionPassword} onChange={(event) => setActionPassword(event.target.value)} /></Field><Field label={useRecovery ? 'Recovery code' : 'Authenticator code'} htmlFor="mfa-action-factor"><input id="mfa-action-factor" inputMode={useRecovery ? undefined : 'numeric'} autoComplete={useRecovery ? 'off' : 'one-time-code'} value={actionFactor} onChange={(event) => setActionFactor(useRecovery ? event.target.value.toUpperCase() : event.target.value.replace(/\D/g, '').slice(0, 6))} placeholder={useRecovery ? 'ABCD-EFGH-JKLM' : '000000'} /></Field><button type="button" className="text-button" onClick={() => { setUseRecovery((value) => !value); setActionFactor(''); setError(''); }}>{useRecovery ? 'Use authenticator code' : 'Use a recovery code'}</button><div className="mfa-enabled-controls__actions"><Button variant="secondary" icon={RefreshCw} onClick={() => void regenerate()} disabled={busy}>Regenerate recovery codes</Button><Button variant="secondary" icon={ShieldOff} onClick={() => void disable()} disabled={busy}>Disable MFA</Button></div></div>
    </div> : null}
  </section>;
}

function RecoveryCodes({ codes, onCopy }: { codes: string[]; onCopy: () => void }) {
  return <div className="mfa-recovery-codes"><div>{codes.map((code) => <code key={code}>{code}</code>)}</div><Button type="button" variant="secondary" icon={Copy} onClick={() => void navigator.clipboard.writeText(codes.join('\n')).then(onCopy)}>Copy all</Button></div>;
}
