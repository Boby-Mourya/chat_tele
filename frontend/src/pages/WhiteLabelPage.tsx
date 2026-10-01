import { ArrowLeft, Image, Palette, RefreshCw, Save } from 'lucide-react';
import { useEffect, useRef, useState, type ChangeEvent, type CSSProperties, type FormEvent } from 'react';
import { Link } from 'react-router-dom';
import { WorkspaceNavigation } from '@/components/workspace-navigation';
import { useToast, useWorkspace } from '@/components/providers';
import { Badge, Button, Card, Field, PageLoader, Switch } from '@/components/ui';
import { readBrandImage } from '@/lib/brand-assets';
import { workspaceApi, workspaceDefaults, type WhiteLabelSettings, type WorkspaceSettings } from '@/lib/workspace-api';

export function WhiteLabelPage() {
  const { pushToast } = useToast();
  const { activeWorkspace } = useWorkspace();
  const [workspace, setWorkspace] = useState<WorkspaceSettings | null>(null);
  const [saved, setSaved] = useState<WhiteLabelSettings | null>(null);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);
  const uploadContext = useRef(activeWorkspace?.id);
  uploadContext.current = activeWorkspace?.id;
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let current = true;
    void workspaceApi.get().then((value) => {
      if (current) { setWorkspace(value); setSaved(value.whiteLabel); setError(''); }
    }).catch((reason: unknown) => { if (current) setError(reason instanceof Error ? reason.message : 'Brand settings could not be loaded'); });
    return () => { current = false; };
  }, [activeWorkspace?.id, attempt]);
  const dirty = !!workspace && !!saved && JSON.stringify(workspace.whiteLabel) !== JSON.stringify(saved);
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ''; };
    window.addEventListener('beforeunload', warn); return () => window.removeEventListener('beforeunload', warn);
  }, [dirty]);
  if (!workspace || !saved) return error ? <div className="page"><h2>White label could not be loaded</h2><p role="alert">{error}</p><Button onClick={() => setAttempt((value) => value + 1)}>Retry</Button></div> : <PageLoader />;
  const brand = workspace.whiteLabel;
  const canPublish = workspace.permissions?.includes('branding.publish') ?? false;
  const setBrand = (patch: Partial<WhiteLabelSettings>) => setWorkspace({ ...workspace, whiteLabel: { ...brand, ...patch } });
  const previewStyle = { '--wl-primary': brand.primaryColor, '--wl-secondary': brand.secondaryColor } as CSSProperties;
  async function save(event?: FormEvent) {
    event?.preventDefault(); if (!canPublish) return;
    setSaving(true); setError('');
    try {
      const next = await workspaceApi.update({ whiteLabel: brand });
      setWorkspace(next); setSaved(next.whiteLabel); pushToast('Dashboard branding saved and applied');
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Branding was not saved'); }
    finally { setSaving(false); }
  }
  function upload(key: 'logoDataUrl' | 'faviconDataUrl' | 'appIconDataUrl') {
    return (event: ChangeEvent<HTMLInputElement>) => {
      const file = event.target.files?.[0];
      if (!file) return;
      if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type) || file.size > 350_000) { setError('Use a PNG, JPG or non-animated WebP smaller than 350 KB'); return; }
      const workspaceId = activeWorkspace?.id;
      setUploading(true); setError('');
      void readBrandImage(file).then((value) => {
        if (uploadContext.current === workspaceId) setWorkspace((current) => current ? { ...current, whiteLabel: { ...current.whiteLabel, [key]: value } } : current);
      }).catch((reason: unknown) => {
        if (uploadContext.current === workspaceId) setError(reason instanceof Error ? reason.message : 'The image could not be read');
      }).finally(() => { if (uploadContext.current === workspaceId) setUploading(false); });
    };
  }
  return <div className="page workspace-console-page white-label-page" style={previewStyle}>
    <div className="page-heading page-heading--split white-label-title"><div><Link to="/workspace" className="white-label-back"><ArrowLeft />Workspace</Link><h2>White label</h2><p>Preview your dashboard identity before applying it to this workspace.</p></div>
      <div className="white-label-heading-actions"><Badge tone={dirty ? 'warning' : 'success'}>{dirty ? 'Unsaved changes' : 'Saved'}</Badge><Button variant="secondary" disabled={!dirty || saving} onClick={() => setBrand(saved)}><RefreshCw />Discard changes</Button><Button disabled={!dirty || saving || uploading || !canPublish} onClick={() => void save()}><Save />{uploading ? 'Preparing image…' : saving ? 'Saving…' : 'Save and apply'}</Button></div></div>
    {error ? <p className="setup-error" role="alert">{error}</p> : null}
    {workspace.brandingWarnings?.length ? <p role="status">Some legacy settings need attention: {workspace.brandingWarnings.join(', ')}. Stored values have not been deleted; re-upload or update them before saving.</p> : null}
    {!canPublish ? <p role="status">You can view this configuration. An authorized workspace administrator must publish changes.</p> : null}
    <div className="workspace-console-layout white-label-layout">
      <WorkspaceNavigation active="white-label" onSelect={(id) => { window.location.href = id === 'workspace' ? '/workspace' : `/workspace?section=${id}`; }} />
      <form className="white-label-editor" onSubmit={(event) => void save(event)}>
        <Card className="workspace-panel"><div className="workspace-panel__heading"><span><Image /></span><div><h3>Brand identity</h3><p>Dashboard logo, browser icon and display name.</p></div></div><div className="workspace-panel__body">
          <div className="white-label-assets">{([['logoDataUrl', 'Logo'], ['faviconDataUrl', 'Favicon'], ['appIconDataUrl', 'Application icon']] as const).map(([key, label]) =>
            <div className="white-label-asset" key={key}><div>{brand[key] ? <img src={brand[key]} alt={`${label} preview`} /> : <span>{brand.companyName.charAt(0)}</span>}</div><section><strong>{label}</strong><small>PNG / JPG / WebP · 350 KB</small><label>Upload<input type="file" accept="image/png,image/jpeg,image/webp" disabled={!canPublish || saving || uploading} onChange={upload(key)} /></label><button type="button" disabled={!canPublish || saving || uploading} onClick={() => setBrand({ [key]: '' })}>Remove</button></section></div>)}</div>
          <div className="two-fields"><Field label="Company / product name"><input value={brand.companyName} maxLength={160} required disabled={!canPublish} onChange={(event) => setBrand({ companyName: event.target.value })} /></Field><Field label="Browser title"><input value={brand.browserTitle} maxLength={120} required disabled={!canPublish} onChange={(event) => setBrand({ browserTitle: event.target.value })} /></Field></div>
          <div className="two-fields"><Field label="Support email"><input type="email" value={brand.supportEmail ?? ''} disabled={!canPublish} onChange={(event) => setBrand({ supportEmail: event.target.value || null })} /></Field><Field label="Support URL"><input type="url" placeholder="https://" value={brand.supportUrl} disabled={!canPublish} onChange={(event) => setBrand({ supportUrl: event.target.value })} /></Field></div>
        </div></Card>
        <Card className="workspace-panel"><div className="workspace-panel__heading"><span><Palette /></span><div><h3>Dashboard theme</h3><p>Primary actions and secondary actions retain contrasting text.</p></div></div><div className="workspace-panel__body"><div className="two-fields">
          <Field label="Primary color"><input type="color" value={brand.primaryColor} disabled={!canPublish} onChange={(event) => setBrand({ primaryColor: event.target.value })} /></Field>
          <Field label="Secondary color"><input type="color" value={brand.secondaryColor} disabled={!canPublish} onChange={(event) => setBrand({ secondaryColor: event.target.value })} /></Field></div>
          <Switch checked={brand.brandedDashboard} disabled={!canPublish} onChange={(value) => setBrand({ brandedDashboard: value })} label="Apply dashboard branding" description="Turning this off restores the platform identity while retaining your saved settings." />
          <Button type="button" variant="secondary" disabled={!canPublish || saving || uploading} onClick={() => setBrand({ ...workspaceDefaults.whiteLabel, brandedDashboard: false })}>Prepare platform defaults</Button>
        </div></Card>
        <Card className="workspace-panel"><div className="workspace-panel__body"><h3>Custom domain and other surfaces</h3>
          <p>Use the canonical <Link to="/workspace/settings/branding">Branding control center</Link> for verified domains, TLS, branded email, authentication, widgets, publication, versions, and rollback.</p>
          {brand.customDomain ? <p>Previously configured hostname: <code>{brand.customDomain}</code>. Open the control center to review its verification state.</p> : null}
          <p>Application icon and support contact remain compatible with this legacy editor; new changes should be published from the control center.</p>
        </div></Card>
        <Button type="submit" disabled={!dirty || saving || uploading || !canPublish}>Save and apply dashboard branding</Button>
      </form>
      <aside className="white-label-preview" aria-label="Unsaved dashboard brand preview"><div className="white-label-preview__top">Dashboard preview — sample presentation</div><div className="white-label-preview__canvas"><div className="white-label-browser"><div className="white-label-browser__bar"><span>{brand.browserTitle}</span></div>
        <div className="setup-resource">{brand.logoDataUrl ? <img src={brand.logoDataUrl} alt="Logo preview" style={{ maxWidth: 180, maxHeight: 64 }} /> : null}<h3>{brand.companyName}</h3><p>Your authorized workspace content remains unchanged.</p><span style={{ display: 'inline-block', width: 48, height: 24, background: brand.primaryColor }} aria-label="Primary color preview" /> <span style={{ display: 'inline-block', width: 48, height: 24, background: brand.secondaryColor }} aria-label="Secondary color preview" /><p>Colors and images here are a preview. Save and apply changes to update the dashboard.</p></div>
      </div></div></aside>
    </div>
  </div>;
}
