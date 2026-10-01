import { Card, Button, Field, Switch } from '@/components/ui';
import { MFASecurityPanel } from '@/components/mfa-security-panel';
import type { WorkspaceSettingsBundle } from './workspaceSettings.api';

const splitLines = (value: string) => value.split(/[\n,]/).map((item) => item.trim()).filter(Boolean);

export function WorkspaceSecuritySettings({
  bundle,
  disabled,
  onBundle,
  onSave,
}: {
  bundle: WorkspaceSettingsBundle;
  disabled: boolean;
  onBundle: (value: WorkspaceSettingsBundle) => void;
  onSave: () => void;
}) {
  const security = bundle.security;
  const update = (next: Partial<typeof security>) => onBundle({ ...bundle, security: { ...security, ...next } });
  return <>
    <Card className="workspace-panel"><div className="workspace-panel__body">
      <h3>Workspace security</h3><p>These controls are persisted and enforced at the relevant workspace authentication, request, invitation, and integration boundaries.</p>
      <Switch checked={security.sensitiveDataMasking} disabled={disabled} onChange={(sensitiveDataMasking) => update({ sensitiveDataMasking })} label="Sensitive data masking" description="Keep sensitive values masked in workspace surfaces that use the existing masking policy." />
      <Field label="MFA enforcement"><select disabled={disabled} value={security.mfaEnforcement} onChange={(event) => update({ mfaEnforcement: event.target.value as 'optional' | 'admins' | 'all' })}><option value="optional">Optional</option><option value="admins">Workspace administrators</option><option value="all">All workspace members</option></select></Field>
      <div className="two-fields"><Field label="Session timeout (minutes)"><input type="number" min={15} max={43200} disabled={disabled} value={security.sessionTimeoutMinutes} onChange={(event) => update({ sessionTimeoutMinutes: Number(event.target.value) })} /></Field><Field label="Password minimum length"><input type="number" min={8} max={128} disabled={disabled} value={security.passwordMinLength} onChange={(event) => update({ passwordMinLength: Number(event.target.value) })} /><small>Enforced when a new account is created from an invitation to this workspace. Existing account passwords remain account-level credentials.</small></Field></div>
      <Field label="IP allowlist"><textarea disabled={disabled} value={security.ipAllowlist.join('\n')} placeholder={'203.0.113.10\n10.0.0.0/8'} onChange={(event) => update({ ipAllowlist: splitLines(event.target.value) })} /><small>When non-empty, requests must originate from one of these addresses/CIDRs.</small></Field>
      <Field label="IP denylist"><textarea disabled={disabled} value={security.ipDenylist.join('\n')} placeholder={'198.51.100.0/24'} onChange={(event) => update({ ipDenylist: splitLines(event.target.value) })} /></Field>
      <Field label="Trusted invitation domains"><textarea disabled={disabled} value={security.trustedDomains.join('\n')} placeholder={'example.com\nsubsidiary.example.com'} onChange={(event) => update({ trustedDomains: splitLines(event.target.value) })} /><small>When configured, new workspace invitations are limited to these email domains.</small></Field>
      <Field label="Security contact"><input type="email" disabled={disabled} value={security.securityContact ?? ''} onChange={(event) => update({ securityContact: event.target.value || null })} /></Field>
      <Switch checked={security.webhookSigningRequired} disabled={disabled} onChange={(webhookSigningRequired) => update({ webhookSigningRequired })} label="Require webhook signing" description="Workspace webhook integrations must keep signature verification enabled." />
      <Switch checked={security.securityNotifications} disabled={disabled} onChange={(securityNotifications) => update({ securityNotifications })} label="Security notifications" />
      <div className="workspace-panel__actions"><Button disabled={disabled} onClick={onSave}>Save security policy</Button></div>
    </div></Card>
    <MFASecurityPanel />
  </>;
}
