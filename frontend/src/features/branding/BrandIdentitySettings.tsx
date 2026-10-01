import { Card, Field, Switch } from '@/components/ui';
import type { ExtendedBranding } from '@/features/workspace/settings/workspaceSettings.api';

export function BrandIdentitySettings({ value, onChange }: { value: ExtendedBranding; onChange: (value: ExtendedBranding) => void }) {
  const identity = value.identity;
  const assets = value.assets;
  const updateIdentity = (next: Partial<typeof identity>) => onChange({ ...value, identity: { ...identity, ...next } });
  const updateAssets = (next: Partial<typeof assets>) => onChange({ ...value, assets: { ...assets, ...next } });
  return <Card className="workspace-panel"><div className="workspace-panel__body">
    <h3>Brand identity</h3><p>Workspace-owned product identity and surface-specific assets.</p>
    <div className="two-fields"><Field label="Company / product name"><input value={identity.companyName} onChange={(event) => updateIdentity({ companyName: event.target.value })} /></Field><Field label="Browser title"><input value={identity.browserTitle} onChange={(event) => updateIdentity({ browserTitle: event.target.value })} /></Field></div>
    <div className="two-fields"><Field label="Primary logo"><input value={identity.logoDataUrl} placeholder="HTTPS URL or data URL" onChange={(event) => updateIdentity({ logoDataUrl: event.target.value })} /></Field><Field label="Compact logo"><input value={assets.compactLogo} onChange={(event) => updateAssets({ compactLogo: event.target.value })} /></Field></div>
    <div className="two-fields"><Field label="Dark-mode logo"><input value={assets.darkModeLogo} onChange={(event) => updateAssets({ darkModeLogo: event.target.value })} /></Field><Field label="Favicon"><input value={identity.faviconDataUrl} onChange={(event) => updateIdentity({ faviconDataUrl: event.target.value })} /></Field></div>
    <div className="two-fields"><Field label="Application icon"><input value={identity.appIconDataUrl} onChange={(event) => updateIdentity({ appIconDataUrl: event.target.value })} /></Field><Field label="Login illustration"><input value={assets.loginIllustration} onChange={(event) => updateAssets({ loginIllustration: event.target.value })} /></Field></div>
    <div className="two-fields"><Field label="Email logo"><input value={assets.emailLogo} onChange={(event) => updateAssets({ emailLogo: event.target.value })} /></Field><Field label="Widget logo"><input value={assets.widgetLogo} onChange={(event) => updateAssets({ widgetLogo: event.target.value })} /></Field></div>
    <div className="two-fields"><Field label="Support email"><input type="email" value={identity.supportEmail ?? ''} onChange={(event) => updateIdentity({ supportEmail: event.target.value || null })} /></Field><Field label="Support URL"><input value={identity.supportUrl} onChange={(event) => updateIdentity({ supportUrl: event.target.value })} /></Field></div>
    <Switch checked={identity.brandedDashboard} onChange={(brandedDashboard) => updateIdentity({ brandedDashboard })} label="Branded dashboard" />
    <Switch checked={identity.brandedLogin} onChange={(brandedLogin) => updateIdentity({ brandedLogin })} label="Branded authentication" />
    <Switch checked={identity.brandedEmails} onChange={(brandedEmails) => updateIdentity({ brandedEmails })} label="Branded emails" />
    <Switch checked={identity.brandedWidget} onChange={(brandedWidget) => updateIdentity({ brandedWidget })} label="Branded chat widget" />
    <Switch checked={identity.removePlatformBranding} onChange={(removePlatformBranding) => updateIdentity({ removePlatformBranding })} label="Remove platform branding" />
  </div></Card>;
}
