import { useMemo, useState } from 'react';
import { Badge, Button, Card, Field, Switch } from '@/components/ui';
import { useToast } from '@/components/providers';
import type { DomainRecord, ExtendedBranding, WorkspaceSettingsBundle } from './workspaceSettings.api';
import { workspaceSettingsApi } from './workspaceSettings.api';

const surfaces = ['identity', 'colors', 'dashboard', 'authentication', 'email', 'widget', 'domains', 'versions'] as const;
const brandColorKeys = ['accent','background','surface','sidebarBackground','sidebarText','header','textPrimary','textSecondary','success','warning','error','border','link'] as const;
type Surface = typeof surfaces[number];

export function WorkspaceBrandingSettings({ bundle, onChange }: { bundle: WorkspaceSettingsBundle; onChange: (next: WorkspaceSettingsBundle) => void }) {
  const { pushToast } = useToast();
  const [surface, setSurface] = useState<Surface>('identity');
  const [saving, setSaving] = useState(false);
  const [hostname, setHostname] = useState('');
  const [note, setNote] = useState('');
  const draft = bundle.brandingDraft;
  const published = bundle.brandingPublished;
  const dirty = useMemo(() => JSON.stringify(draft) !== JSON.stringify(published), [draft, published]);
  const patch = (next: Partial<ExtendedBranding>) => onChange({ ...bundle, brandingDraft: { ...draft, ...next } });

  async function saveDraft() {
    setSaving(true);
    try { const saved = await workspaceSettingsApi.saveBrandDraft(draft); onChange({ ...bundle, brandingDraft: saved }); pushToast('Brand draft saved'); }
    catch (error) { pushToast(error instanceof Error ? error.message : 'Brand draft could not be saved', 'error'); }
    finally { setSaving(false); }
  }
  async function publish() {
    setSaving(true);
    try {
      await workspaceSettingsApi.saveBrandDraft(draft);
      const version = await workspaceSettingsApi.publishBrand(note);
      onChange({ ...bundle, brandingDraft: version.branding, brandingPublished: version.branding, brandingVersions: [...bundle.brandingVersions, version].slice(-50) });
      setNote(''); pushToast(`Brand version ${version.version} published`);
    } catch (error) { pushToast(error instanceof Error ? error.message : 'Brand could not be published', 'error'); }
    finally { setSaving(false); }
  }
  async function addDomain() {
    if (!hostname.trim()) return;
    setSaving(true);
    try { const domain = await workspaceSettingsApi.createDomain(hostname); onChange({ ...bundle, domains: { domains: [...bundle.domains.domains, domain] } }); setHostname(''); pushToast('DNS verification record created'); }
    catch (error) { pushToast(error instanceof Error ? error.message : 'Domain could not be added', 'error'); }
    finally { setSaving(false); }
  }
  async function domainAction(domain: DomainRecord, action: 'verify' | 'disable') {
    setSaving(true);
    try {
      const next = action === 'verify' ? await workspaceSettingsApi.verifyDomain(domain.id) : await workspaceSettingsApi.disableDomain(domain.id);
      onChange({ ...bundle, domains: { domains: bundle.domains.domains.map((item) => item.id === next.id ? next : item) } });
      pushToast(action === 'verify' ? 'Domain verification started' : 'Domain disabled');
    } catch (error) { pushToast(error instanceof Error ? error.message : 'Domain could not be updated', 'error'); }
    finally { setSaving(false); }
  }
  async function rollback(version: number) {
    setSaving(true);
    try {
      const created = await workspaceSettingsApi.rollbackBrand(version, `Rollback to version ${version}`);
      onChange({ ...bundle, brandingDraft: created.branding, brandingPublished: created.branding, brandingVersions: [...bundle.brandingVersions, created].slice(-50) });
      pushToast(`Rolled back using version ${version}`);
    } catch (error) { pushToast(error instanceof Error ? error.message : 'Rollback failed', 'error'); }
    finally { setSaving(false); }
  }

  return <div className="workspace-branding-settings">
    <Card className="workspace-panel"><div className="workspace-panel__body">
      <div className="page-heading page-heading--split"><div><h3>White-label control center</h3><p>Edit a draft, preview it, then publish a version. Existing production branding is unchanged until Publish.</p></div><Badge tone={dirty ? 'warning' : 'success'}>{dirty ? 'Draft differs from published' : 'Published state'}</Badge></div>
      <div className="workspace-branding-tabs">{surfaces.map((item) => <Button key={item} type="button" variant={surface === item ? 'primary' : 'secondary'} onClick={() => setSurface(item)}>{item.replace('_', ' ')}</Button>)}</div>
    </div></Card>

    {surface === 'identity' ? <Card className="workspace-panel"><div className="workspace-panel__body"><h3>Brand identity</h3>
      <div className="two-fields"><Field label="Company / product name"><input value={draft.identity.companyName} onChange={(event) => patch({ identity: { ...draft.identity, companyName: event.target.value } })} /></Field><Field label="Browser title"><input value={draft.identity.browserTitle} onChange={(event) => patch({ identity: { ...draft.identity, browserTitle: event.target.value } })} /></Field></div>
      <div className="two-fields"><Field label="Logo data URL"><input value={draft.identity.logoDataUrl} onChange={(event) => patch({ identity: { ...draft.identity, logoDataUrl: event.target.value } })} /></Field><Field label="Favicon data URL"><input value={draft.identity.faviconDataUrl} onChange={(event) => patch({ identity: { ...draft.identity, faviconDataUrl: event.target.value } })} /></Field></div>
      <div className="two-fields"><Field label="Application icon"><input value={draft.identity.appIconDataUrl} onChange={(event) => patch({ identity: { ...draft.identity, appIconDataUrl: event.target.value } })} /></Field><Field label="Support email"><input type="email" value={draft.identity.supportEmail ?? ''} onChange={(event) => patch({ identity: { ...draft.identity, supportEmail: event.target.value || null } })} /></Field></div>
      <Field label="Support URL"><input value={draft.identity.supportUrl} onChange={(event) => patch({ identity: { ...draft.identity, supportUrl: event.target.value } })} /></Field>
      <Switch checked={draft.identity.brandedDashboard} onChange={(value) => patch({ identity: { ...draft.identity, brandedDashboard: value } })} label="Branded dashboard" />
      <Switch checked={draft.identity.brandedLogin} onChange={(value) => patch({ identity: { ...draft.identity, brandedLogin: value } })} label="Branded authentication" />
      <Switch checked={draft.identity.brandedEmails} onChange={(value) => patch({ identity: { ...draft.identity, brandedEmails: value } })} label="Branded emails" />
      <Switch checked={draft.identity.brandedWidget} onChange={(value) => patch({ identity: { ...draft.identity, brandedWidget: value } })} label="Branded widget" />
      <Switch checked={draft.identity.removePlatformBranding} onChange={(value) => patch({ identity: { ...draft.identity, removePlatformBranding: value } })} label="Remove platform branding" />
    </div></Card> : null}

    {surface === 'colors' ? <Card className="workspace-panel"><div className="workspace-panel__body"><h3>Colors and typography</h3>
      <div className="two-fields"><Field label="Primary"><input type="color" value={draft.identity.primaryColor} onChange={(event) => patch({ identity: { ...draft.identity, primaryColor: event.target.value } })} /></Field><Field label="Secondary"><input type="color" value={draft.identity.secondaryColor} onChange={(event) => patch({ identity: { ...draft.identity, secondaryColor: event.target.value } })} /></Field></div>
      {brandColorKeys.map((key) => <Field key={key} label={key}><input type="color" value={draft.colors[key]} onChange={(event) => patch({ colors: { ...draft.colors, [key]: event.target.value } })} /></Field>)}
      <div className="two-fields"><Field label="Heading font"><input value={String(draft.typography.headingFont ?? 'Inter')} onChange={(event) => patch({ typography: { ...draft.typography, headingFont: event.target.value } })} /></Field><Field label="Body font"><input value={String(draft.typography.bodyFont ?? 'Inter')} onChange={(event) => patch({ typography: { ...draft.typography, bodyFont: event.target.value } })} /></Field></div>
    </div></Card> : null}

    {surface === 'dashboard' ? <DashboardEditor value={draft.dashboard} onChange={(dashboard) => patch({ dashboard })} /> : null}

    {surface === 'authentication' ? <Card className="workspace-panel"><div className="workspace-panel__body"><h3>Branded authentication</h3>
      <div className="two-fields"><Field label="Login title"><input value={draft.authentication.loginTitle} onChange={(e) => patch({ authentication: { ...draft.authentication, loginTitle: e.target.value } })} /></Field><Field label="Login logo"><input value={draft.authentication.loginLogo} onChange={(e) => patch({ authentication: { ...draft.authentication, loginLogo: e.target.value } })} /></Field></div>
      <Field label="Login description"><textarea value={draft.authentication.loginDescription} onChange={(e) => patch({ authentication: { ...draft.authentication, loginDescription: e.target.value } })} /></Field>
      <div className="two-fields"><Field label="Terms URL"><input value={draft.authentication.termsUrl} onChange={(e) => patch({ authentication: { ...draft.authentication, termsUrl: e.target.value } })} /></Field><Field label="Privacy URL"><input value={draft.authentication.privacyUrl} onChange={(e) => patch({ authentication: { ...draft.authentication, privacyUrl: e.target.value } })} /></Field></div>
      <Field label="Footer"><input value={draft.authentication.footer} onChange={(e) => patch({ authentication: { ...draft.authentication, footer: e.target.value } })} /></Field>
    </div></Card> : null}

    {surface === 'email' ? <Card className="workspace-panel"><div className="workspace-panel__body"><h3>Branded emails</h3>
      <div className="two-fields"><Field label="Sender name"><input value={draft.email.senderName} onChange={(e) => patch({ email: { ...draft.email, senderName: e.target.value } })} /></Field><Field label="Reply-to"><input type="email" value={draft.email.replyTo ?? ''} onChange={(e) => patch({ email: { ...draft.email, replyTo: e.target.value || null } })} /></Field></div>
      <Field label="Email logo"><input value={draft.email.logo} onChange={(e) => patch({ email: { ...draft.email, logo: e.target.value } })} /></Field><Field label="Footer"><textarea value={draft.email.footer} onChange={(e) => patch({ email: { ...draft.email, footer: e.target.value } })} /></Field>
      <p>Templates: {draft.email.enabledTemplates.join(', ')}</p>
    </div></Card> : null}

    {surface === 'widget' ? <Card className="workspace-panel"><div className="workspace-panel__body"><h3>Website chat widget</h3>
      <div className="two-fields"><Field label="Greeting"><input value={draft.widget.greeting} onChange={(e) => patch({ widget: { ...draft.widget, greeting: e.target.value } })} /></Field><Field label="Position"><select value={draft.widget.position} onChange={(e) => patch({ widget: { ...draft.widget, position: e.target.value as 'bottom-left' | 'bottom-right' } })}><option value="bottom-right">Bottom right</option><option value="bottom-left">Bottom left</option></select></Field></div>
      <div className="two-fields"><Field label="Launcher color"><input type="color" value={draft.widget.launcherColor} onChange={(e) => patch({ widget: { ...draft.widget, launcherColor: e.target.value } })} /></Field><Field label="Background"><input type="color" value={draft.widget.background} onChange={(e) => patch({ widget: { ...draft.widget, background: e.target.value } })} /></Field></div>
      <Field label="Header"><input value={draft.widget.header} onChange={(e) => patch({ widget: { ...draft.widget, header: e.target.value } })} /></Field><Field label="Privacy link"><input value={draft.widget.privacyUrl} onChange={(e) => patch({ widget: { ...draft.widget, privacyUrl: e.target.value } })} /></Field><Field label="Offline message"><input value={draft.widget.offlineMessage} onChange={(e) => patch({ widget: { ...draft.widget, offlineMessage: e.target.value } })} /></Field>
    </div></Card> : null}

    {surface === 'domains' ? <Card className="workspace-panel"><div className="workspace-panel__body"><h3>Custom domains</h3><p>Verification and certificate provisioning advance through explicit lifecycle states; the browser never marks a domain verified.</p>
      <div className="two-fields"><Field label="Portal hostname"><input placeholder="portal.customer.com" value={hostname} onChange={(e) => setHostname(e.target.value)} /></Field><div><Button type="button" disabled={saving || !hostname.trim()} onClick={() => void addDomain()}>Add domain</Button></div></div>
      {bundle.domains.domains.map((domain) => <div className="setup-resource" key={domain.id}><strong>{domain.hostname}</strong> <Badge>{domain.status}</Badge><p>Add TXT record <code>{domain.verificationName}</code> = <code>{domain.verificationValue}</code></p><Button type="button" variant="secondary" disabled={saving || domain.status === 'active' || domain.status === 'disabled'} onClick={() => void domainAction(domain, 'verify')}>Start verification</Button> <Button type="button" variant="secondary" disabled={saving || domain.status === 'disabled'} onClick={() => void domainAction(domain, 'disable')}>Disable</Button></div>)}
    </div></Card> : null}

    {surface === 'versions' ? <Card className="workspace-panel"><div className="workspace-panel__body"><h3>Publication history</h3>{bundle.brandingVersions.length === 0 ? <p>No published versions yet.</p> : [...bundle.brandingVersions].reverse().map((version) => <div className="setup-resource" key={version.version}><strong>Version {version.version}</strong><p>{new Date(version.publishedAt).toLocaleString()} · {version.changeNote || 'No note'}</p><Button type="button" variant="secondary" disabled={saving} onClick={() => void rollback(version.version)}>Rollback to this version</Button></div>)}</div></Card> : null}

    {!['domains','versions'].includes(surface) ? <Card className="workspace-panel"><div className="workspace-panel__body"><div className="two-fields"><Field label="Publication note"><input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Describe this brand change" /></Field><div className="workspace-panel__actions"><Button type="button" variant="secondary" disabled={saving} onClick={() => void saveDraft()}>Save draft</Button><Button type="button" disabled={saving || !dirty} onClick={() => void publish()}>Publish</Button></div></div></div></Card> : null}
  </div>;
}

function DashboardEditor({ value, onChange }: { value: ExtendedBranding['dashboard']; onChange: (value: ExtendedBranding['dashboard']) => void }) {
  function addWidget() { onChange({ ...value, layoutVersion: value.layoutVersion + 1, widgets: [...value.widgets, { id: crypto.randomUUID(), type: 'conversation-summary', x: 0, y: value.widgets.length * 2, width: 4, height: 2, visible: true, audience: [], config: {} }] }); }
  return <Card className="workspace-panel"><div className="workspace-panel__body"><h3>Dashboard layout</h3><div className="two-fields"><Field label="Landing screen"><input value={value.landingScreen} onChange={(e) => onChange({ ...value, landingScreen: e.target.value })} /></Field><div><Button type="button" onClick={addWidget}>Add widget</Button></div></div>
    {value.widgets.map((widget, index) => <div className="setup-resource" key={widget.id}><div className="two-fields"><Field label="Widget type"><select value={widget.type} onChange={(e) => onChange({ ...value, widgets: value.widgets.map((item, i) => i === index ? { ...item, type: e.target.value } : item) })}><option value="conversation-summary">Conversation summary</option><option value="lead-summary">Lead summary</option><option value="channel-health">Channel health</option><option value="agent-activity">Agent activity</option><option value="crm-status">CRM status</option><option value="education-summary">Education summary</option><option value="usage">Usage</option></select></Field><Field label="Width"><input type="number" min={1} max={24} value={widget.width} onChange={(e) => onChange({ ...value, widgets: value.widgets.map((item, i) => i === index ? { ...item, width: Number(e.target.value) } : item) })} /></Field></div><Switch checked={widget.visible} onChange={(visible) => onChange({ ...value, widgets: value.widgets.map((item, i) => i === index ? { ...item, visible } : item) })} label="Visible" /><Button type="button" variant="secondary" onClick={() => onChange({ ...value, layoutVersion: value.layoutVersion + 1, widgets: value.widgets.filter((_, i) => i !== index) })}>Remove</Button></div>)}
  </div></Card>;
}