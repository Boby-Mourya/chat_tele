import { useEffect, useMemo, useState } from 'react';
import { Button, Card, Field } from '@/components/ui';
import { useToast } from '@/components/providers';
import {
  workspaceSettingsApi,
  type EmailPreview,
  type ExtendedBranding,
} from '@/features/workspace/settings/workspaceSettings.api';

export function BrandEmailSettings({ value, onChange }: { value: ExtendedBranding; onChange: (value: ExtendedBranding) => void }) {
  const { pushToast } = useToast();
  const email = value.email;
  const templateNames = useMemo(() => Object.keys(email.templates), [email.templates]);
  const [selected, setSelected] = useState(templateNames[0] ?? 'invitation');
  const [recipient, setRecipient] = useState('');
  const [preview, setPreview] = useState<EmailPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const template = email.templates[selected];

  useEffect(() => {
    if (!templateNames.includes(selected) && templateNames[0]) setSelected(templateNames[0]);
  }, [selected, templateNames]);

  const updateEmail = (next: Partial<typeof email>) => onChange({ ...value, email: { ...email, ...next } });
  function updateTemplate(next: Partial<NonNullable<typeof template>>) {
    if (!template) return;
    updateEmail({ templates: { ...email.templates, [selected]: { ...template, ...next } } });
  }
  async function doPreview() {
    setBusy(true);
    try { setPreview(await workspaceSettingsApi.previewEmail(selected, email)); }
    catch (reason) { pushToast(reason instanceof Error ? reason.message : 'Email preview failed', 'error'); }
    finally { setBusy(false); }
  }
  async function sendTest() {
    if (!recipient.trim()) return;
    setBusy(true);
    try { setPreview(await workspaceSettingsApi.testEmail(selected, email, recipient)); pushToast(`Test email prepared for ${recipient}`); }
    catch (reason) { pushToast(reason instanceof Error ? reason.message : 'Test email failed', 'error'); }
    finally { setBusy(false); }
  }

  return <Card className="workspace-panel"><div className="workspace-panel__body">
    <h3>Branded email</h3><p>Edit workspace email templates, preview server-rendered output, and send a test using the configured delivery service.</p>
    <div className="two-fields"><Field label="Sender name"><input value={email.senderName} onChange={(event) => updateEmail({ senderName: event.target.value })} /></Field><Field label="Reply-to"><input type="email" value={email.replyTo ?? ''} onChange={(event) => updateEmail({ replyTo: event.target.value || null })} /></Field></div>
    <Field label="Email logo"><input value={email.logo} onChange={(event) => updateEmail({ logo: event.target.value })} /></Field>
    <Field label="Footer"><textarea value={email.footer} onChange={(event) => updateEmail({ footer: event.target.value })} /></Field>
    <Field label="Template"><select value={selected} onChange={(event) => setSelected(event.target.value)}>{templateNames.map((name) => <option key={name} value={name}>{name.replaceAll('_', ' ')}</option>)}</select></Field>
    {template ? <div className="setup-resource">
      <label><input type="checkbox" checked={email.enabledTemplates.includes(selected)} onChange={(event) => updateEmail({ enabledTemplates: event.target.checked ? [...new Set([...email.enabledTemplates, selected])] : email.enabledTemplates.filter((name) => name !== selected) })} /> Enable this template</label>
      <Field label="Subject"><input value={template.subject} onChange={(event) => updateTemplate({ subject: event.target.value })} /></Field>
      <Field label="Heading"><input value={template.heading} onChange={(event) => updateTemplate({ heading: event.target.value })} /></Field>
      <Field label="Body"><textarea value={template.body} onChange={(event) => updateTemplate({ body: event.target.value })} /></Field>
      <Field label="Button label"><input value={template.buttonLabel} onChange={(event) => updateTemplate({ buttonLabel: event.target.value })} /></Field>
      <small>Supported placeholders include {'{{company_name}}'}, {'{{workspace_name}}'}, and {'{{inviter_name}}'} where relevant.</small>
    </div> : null}
    <div className="two-fields"><Field label="Test recipient"><input type="email" value={recipient} onChange={(event) => setRecipient(event.target.value)} /></Field><div className="workspace-panel__actions"><Button type="button" variant="secondary" disabled={busy || !template} onClick={() => void doPreview()}>Preview</Button><Button type="button" disabled={busy || !recipient.trim() || !template} onClick={() => void sendTest()}>Send test</Button></div></div>
    {preview ? <div className="setup-resource"><strong>{preview.subject}</strong><pre>{preview.text}</pre><details><summary>Rendered HTML</summary><iframe title="Email preview" sandbox="" srcDoc={preview.html} style={{ width: '100%', minHeight: 260, border: 0 }} /></details></div> : null}
  </div></Card>;
}
