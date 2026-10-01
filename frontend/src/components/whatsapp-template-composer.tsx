import { WhatsApp } from '@/components/provider-logo';
import { apiErrorMessage } from '@/lib/api-error-message';
import { useEffect, useMemo, useState } from 'react';
import { Check, Copy, ExternalLink, FileText, PencilLine, Plus, Sparkles, Trash2 } from 'lucide-react';
import { Button, Field, Modal } from '@/components/ui';
import { api } from '@/lib/api';
import { purposeTemplateLabels, whatsappTemplateLibrary, type TemplateButton, type WhatsAppTemplateDraft } from '@/lib/whatsapp-template-library';
import type { AgentPurpose } from '@/types';
import './whatsapp-template-composer.css';

type ProviderTemplate = Awaited<ReturnType<typeof api.integrations.whatsapp.templates>>[number];
type Mode = 'library' | 'approved';
const cloneDraft = (draft: WhatsAppTemplateDraft): WhatsAppTemplateDraft => ({ ...draft, buttons: draft.buttons.map((button) => ({ ...button })) });
const variables = (draft: WhatsAppTemplateDraft) => [...new Set(`${draft.header} ${draft.body} ${draft.footer} ${draft.buttons.map((button) => button.value ?? '').join(' ')}`.match(/{{\d+}}/g) ?? [])];
const draftText = (draft: WhatsAppTemplateDraft) => [draft.header, draft.body, draft.footer, ...draft.buttons.map((button) => `${button.type}: ${button.text}${button.value ? ` — ${button.value}` : ''}`)].filter(Boolean).join('\n\n');

export function WhatsAppTemplateComposer({ agentId, conversationId, purpose = 'support', onQueued }: { agentId: string; conversationId: string; purpose?: AgentPurpose | null; onQueued?: () => void }) {
  const initialPurpose = purpose ?? 'support';
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<Mode>('library');
  const [selectedPurpose, setSelectedPurpose] = useState<AgentPurpose>(initialPurpose);
  const samples = useMemo(() => whatsappTemplateLibrary.filter((item) => item.purpose === selectedPurpose), [selectedPurpose]);
  const [draft, setDraft] = useState<WhatsAppTemplateDraft>(() => cloneDraft(whatsappTemplateLibrary.find((item) => item.purpose === initialPurpose)!));
  const [templates, setTemplates] = useState<ProviderTemplate[]>([]);
  const [index, setIndex] = useState('');
  const [values, setValues] = useState<string[]>([]);
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [sent, setSent] = useState(false);
  const approvedTemplate = index === '' ? undefined : templates[Number(index)];

  useEffect(() => {
    if (!open) return;
    let active = true;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLoading(true); setError(''); setNotice(''); setSent(false); setIndex(''); setValues([]); setConsent(false); setMode('library'); setSelectedPurpose(initialPurpose);
    const first = whatsappTemplateLibrary.find((item) => item.purpose === initialPurpose);
    if (first) setDraft(cloneDraft(first));
    void api.integrations.whatsapp.templates(agentId).then((items) => { if (active) setTemplates(items); })
      .catch((failure: unknown) => { if (active) setError(failure instanceof Error ? failure.message : 'Could not load approved templates'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [open, agentId, initialPurpose]);

  const chooseApproved = (value: string) => { setIndex(value); const next = templates[Number(value)]; setValues(next?.fields.map(() => '') ?? []); };
  const send = async () => {
    if (!approvedTemplate || !consent || busy) return;
    setBusy(true); setError('');
    try { await api.integrations.whatsapp.sendTemplate(conversationId, { name: approvedTemplate.name, language: approvedTemplate.language, parameters: values, consentConfirmed: true }); setSent(true); onQueued?.(); }
    catch (failure) { setError(apiErrorMessage(failure, 'Could not queue template')); }
    finally { setBusy(false); }
  };
  const useDraft = () => {
    const approvedIndex = templates.findIndex((item) => item.name === draft.name);
    if (approvedIndex >= 0) { chooseApproved(String(approvedIndex)); setMode('approved'); setNotice('Matching approved template selected. Fill its variables and queue it.'); }
    else setNotice('Draft ready. Copy it into WhatsApp Manager, submit it for approval, then refresh the approved list here.');
  };
  const copyDraft = async () => {
    try { await navigator.clipboard.writeText(draftText(draft)); setNotice('Editable template copied to clipboard.'); }
    catch { setNotice('Copy is unavailable in this browser. Select the draft text manually.'); }
  };

  return <><Button variant="secondary" size="sm" icon={WhatsApp} onClick={() => setOpen(true)}>Send WhatsApp template</Button><Modal open={open} onClose={() => { if (!busy) setOpen(false); }} closeDisabled={busy} size="lg" title="WhatsApp template studio" description="Choose an industry-ready starting point, tailor it to your brand, then send the matching Meta-approved template." footer={<><Button variant="secondary" disabled={busy} onClick={() => setOpen(false)}>Close</Button>{mode === 'library' ? <Button icon={Copy} onClick={() => void copyDraft()}>Copy draft</Button> : !sent ? <Button disabled={loading || busy || !approvedTemplate || Boolean(approvedTemplate.unsupportedReason) || !consent || values.some((value) => !value.trim())} onClick={() => void send()}>{busy ? 'Queueing…' : 'Queue template'}</Button> : null}</>}>
    <div className="wa-template-studio"><div className="wa-template-mode" role="tablist" aria-label="Template source"><button type="button" role="tab" aria-selected={mode === 'library'} className={mode === 'library' ? 'is-active' : ''} onClick={() => setMode('library')}><Sparkles />Template library <span>{whatsappTemplateLibrary.length}</span></button><button type="button" role="tab" aria-selected={mode === 'approved'} className={mode === 'approved' ? 'is-active' : ''} onClick={() => setMode('approved')}><Check />Approved by Meta <span>{templates.length}</span></button></div>
      {error ? <p className="wa-template-alert" role="alert">{error}</p> : null}{notice ? <p className="wa-template-notice" role="status">{notice}</p> : null}
      {mode === 'library' ? <Library selectedPurpose={selectedPurpose} setSelectedPurpose={(next) => { setSelectedPurpose(next); const first = whatsappTemplateLibrary.find((item) => item.purpose === next); if (first) setDraft(cloneDraft(first)); setNotice(''); }} samples={samples} draft={draft} setDraft={setDraft} useDraft={useDraft} /> : <Approved templates={templates} loading={loading} index={index} choose={chooseApproved} template={approvedTemplate} values={values} setValues={setValues} consent={consent} setConsent={setConsent} busy={busy} sent={sent} />}
    </div>
  </Modal></>;
}

function Library({ selectedPurpose, setSelectedPurpose, samples, draft, setDraft, useDraft }: { selectedPurpose: AgentPurpose; setSelectedPurpose: (purpose: AgentPurpose) => void; samples: WhatsAppTemplateDraft[]; draft: WhatsAppTemplateDraft; setDraft: (draft: WhatsAppTemplateDraft) => void; useDraft: () => void }) {
  const patch = (next: Partial<WhatsAppTemplateDraft>) => setDraft({ ...draft, ...next });
  const patchButton = (index: number, next: Partial<TemplateButton>) => patch({ buttons: draft.buttons.map((button, position) => position === index ? { ...button, ...next } : button) });
  return <><div className="wa-purpose-tabs" role="tablist" aria-label="Business purpose">{(['education', 'support', 'lead_generation'] as AgentPurpose[]).map((item) => <button type="button" role="tab" aria-selected={selectedPurpose === item} className={selectedPurpose === item ? 'is-active' : ''} key={item} onClick={() => setSelectedPurpose(item)}>{purposeTemplateLabels[item]}<span>{whatsappTemplateLibrary.filter((sample) => sample.purpose === item).length}</span></button>)}</div>
    <div className="wa-template-layout"><aside className="wa-template-gallery" aria-label={`${purposeTemplateLabels[selectedPurpose]} templates`}>{samples.map((sample) => <button type="button" key={sample.id} className={draft.id === sample.id ? 'is-active' : ''} onClick={() => setDraft(cloneDraft(sample))}><span><FileText /><em>{sample.category}</em></span><strong>{sample.occasion}</strong><small>{sample.header}</small></button>)}</aside>
      <div className="wa-template-editor"><div className="wa-template-editor__heading"><div><PencilLine /><span><strong>Edit your template</strong><small>Every word, variable, and action is editable</small></span></div><Button size="sm" onClick={useDraft}>Use this template</Button></div>
        <div className="wa-template-editor__grid"><Field label="Template name"><input value={draft.name} onChange={(event) => patch({ name: event.target.value.toLowerCase().replace(/[^a-z0-9_]/g, '_') })} /></Field><Field label="Meta category"><select value={draft.category} onChange={(event) => patch({ category: event.target.value as WhatsAppTemplateDraft['category'] })}><option value="UTILITY">Utility</option><option value="MARKETING">Marketing</option></select></Field></div>
        <Field label="Header"><input maxLength={60} value={draft.header} onChange={(event) => patch({ header: event.target.value })} /></Field><Field label="Message"><textarea rows={8} maxLength={1024} value={draft.body} onChange={(event) => patch({ body: event.target.value })} /></Field><Field label="Footer"><input maxLength={60} value={draft.footer} onChange={(event) => patch({ footer: event.target.value })} /></Field>
        <div className="wa-template-buttons"><div><strong>Actions</strong><button type="button" disabled={draft.buttons.length >= 3} onClick={() => patch({ buttons: [...draft.buttons, { type: 'quick_reply', text: 'New action' }] })}><Plus />Add action</button></div>{draft.buttons.map((button, index) => <div key={`${index}-${button.type}`}><select aria-label={`Action ${index + 1} type`} value={button.type} onChange={(event) => patchButton(index, { type: event.target.value as TemplateButton['type'] })}><option value="quick_reply">Quick reply</option><option value="url">Website</option><option value="phone">Phone</option></select><input aria-label={`Action ${index + 1} label`} maxLength={25} value={button.text} onChange={(event) => patchButton(index, { text: event.target.value })} />{button.type !== 'quick_reply' ? <input aria-label={`Action ${index + 1} value`} value={button.value ?? ''} placeholder={button.type === 'url' ? 'https://…' : '+91…'} onChange={(event) => patchButton(index, { value: event.target.value })} /> : <span /> }<button type="button" aria-label={`Remove action ${index + 1}`} onClick={() => patch({ buttons: draft.buttons.filter((_, position) => position !== index) })}><Trash2 /></button></div>)}</div>
        <div className="wa-template-variables"><strong>Variables</strong>{variables(draft).map((variable) => <code key={variable}>{variable}</code>)}<small>Keep variables sequential when submitting to Meta.</small></div>
      </div><DraftPreview draft={draft} /></div></>;
}

function DraftPreview({ draft }: { draft: WhatsAppTemplateDraft }) {
  return <aside className="wa-template-preview"><div className="wa-template-preview__label"><WhatsApp />Live preview</div><div className="wa-template-phone"><div className="wa-template-phone__bar"><span>Business</span><small>online</small></div><div className="wa-template-phone__chat"><article><strong>{draft.header}</strong><p>{draft.body}</p><small>{draft.footer}</small><time>10:42 ✓✓</time>{draft.buttons.length ? <div>{draft.buttons.map((button, index) => <button type="button" key={`${button.text}-${index}`}>{button.type === 'url' ? <ExternalLink /> : null}{button.text || 'Action'}</button>)}</div> : null}</article></div></div><p>Preview uses sample variables. Meta reviews the final wording, category, and actions.</p></aside>;
}

function Approved({ templates, loading, index, choose, template, values, setValues, consent, setConsent, busy, sent }: { templates: ProviderTemplate[]; loading: boolean; index: string; choose: (value: string) => void; template?: ProviderTemplate; values: string[]; setValues: (values: string[]) => void; consent: boolean; setConsent: (value: boolean) => void; busy: boolean; sent: boolean }) {
  if (sent) return <div className="wa-template-success" role="status"><Check /><h3>Template queued</h3><p>Check WhatsApp message activity for delivery confirmation.</p></div>;
  if (loading) return <p>Loading approved templates from Meta…</p>;
  return <div className="wa-approved-layout"><div className="whatsapp-form"><Field label="Approved template" htmlFor="wa-template"><select id="wa-template" value={index} disabled={busy} onChange={(event) => choose(event.target.value)}><option value="">Choose a template</option>{templates.map((item, i) => <option key={`${item.name}-${item.language}`} value={i}>{item.name} ({item.language})</option>)}</select></Field>{!templates.length ? <p>No approved templates found. Choose a sample from the library, tailor it, and submit it in WhatsApp Manager for approval.</p> : null}{template ? <><div className="wa-approved-preview">{template.preview}</div>{template.unsupportedReason ? <p role="alert">{template.unsupportedReason}</p> : template.fields.map((field, i) => <Field key={`${field.component}-${field.name}`} label={`${field.component} ${field.name}`} htmlFor={`wa-param-${i}`}><input id={`wa-param-${i}`} value={values[i] ?? ''} maxLength={1024} disabled={busy} onChange={(event) => setValues(values.map((value, j) => i === j ? event.target.value : value))} /></Field>)}</> : null}<label className="wa-template-consent"><input type="checkbox" checked={consent} disabled={busy} onChange={(event) => setConsent(event.target.checked)} /> This customer opted in to receive these WhatsApp messages.</label></div></div>;
}
