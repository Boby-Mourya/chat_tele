import { AgentStatusControl } from '@/components/agent-status-control';
import '@/components/bot-enrollment-panel.css';
import { Facebook, Instagram } from '@/components/social-icons';
import { BookOpen, Bot, Check, ChevronLeft, ChevronRight, Code2, Copy, Ellipsis, Globe2, Hash, LayoutGrid, List, MessageSquare, MoreHorizontal, Plus, Search, SendHorizontal, Sparkles, Trash2, Users, Zap } from 'lucide-react';
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useToast } from '@/components/providers';
import { Badge, Button, Card, EmptyState, Field, Modal, PageLoader } from '@/components/ui';
import { api, ApiError } from '@/lib/api';
import { formatCompact, relativeTime } from '@/lib/format';
import { useApi } from '@/lib/use-api';
import { getWidgetLocale, supportedWidgetLanguages } from '@/lib/widget-localization';
import type { Agent, AgentPurpose, AgentTone, DeploymentChannel, WhatsAppConnection } from '@/types';

const purposeOptions: Array<{ id: AgentPurpose; icon: typeof Bot; name: string; description: string; template: string }> = [
  { id: 'support', icon: MessageSquare, name: 'General / Support', description: 'Answer support, onboarding, and general knowledge questions.', template: 'support' },
  { id: 'lead_generation', icon: Bot, name: 'Lead generation', description: 'Capture, qualify, and prepare inbound leads for CRM workflows.', template: 'lead' },
  { id: 'education', icon: BookOpen, name: 'Education', description: 'Serve authorized students using course and enrollment-aware access.', template: 'education' },
];

const purposeLabels: Record<AgentPurpose, string> = {
  support: 'General / Support',
  lead_generation: 'Lead generation',
  education: 'Education',
};

const deploymentOptions: Array<{ id: DeploymentChannel; icon: typeof Globe2; name: string; description: string }> = [
  { id: 'website', icon: Globe2, name: 'Website', description: 'Use the website chat widget.' },
  { id: 'whatsapp', icon: MessageSquare, name: 'WhatsApp', description: 'Use the WhatsApp Business template.' },
  { id: 'telegram', icon: SendHorizontal, name: 'Telegram', description: 'Connect a Telegram bot using BotFather.' },
  { id: 'instagram', icon: Instagram, name: 'Instagram', description: 'Use the Instagram DM template.' },
  { id: 'facebook', icon: Facebook, name: 'Facebook / Meta', description: 'Use the Messenger template.' },
  { id: 'slack', icon: Hash, name: 'Slack', description: 'Use the Slack conversation template.' },
  { id: 'teams', icon: Users, name: 'Microsoft Teams', description: 'Use the Teams conversation template.' },
  { id: 'api', icon: Code2, name: 'Developer API', description: 'Use the API response template.' },
  { id: 'notion', icon: BookOpen, name: 'Notion', description: 'Use the knowledge-sync template.' },
  { id: 'zapier', icon: Zap, name: 'Zapier', description: 'Use the workflow template.' },
];

function agentPurpose(agent: Agent): AgentPurpose {
  return agent.purpose ?? 'support';
}

export function AgentsPage() {
  const result = useApi(() => api.agents.list()); const { pushToast } = useToast(); const navigate = useNavigate();
  const [search, setSearch] = useState(''); const [view, setView] = useState<'grid' | 'list'>('grid'); const [createOpen, setCreateOpen] = useState(false); const [duplicateAgent, setDuplicateAgent] = useState<Agent | null>(null); const [purposeAgent, setPurposeAgent] = useState<Agent | null>(null); const [deleteAgent, setDeleteAgent] = useState<Agent | null>(null);
  const filtered = result.data?.filter((agent) => `${agent.name} ${agent.description} ${purposeLabels[agentPurpose(agent)]}`.toLowerCase().includes(search.toLowerCase())) ?? [];
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState('');
  const closeDelete = () => { if (!deleting) { setDeleteAgent(null); setDeleteError(''); } };
  const remove = async () => {
    if (!deleteAgent || deleting) return;
    setDeleting(true); setDeleteError('');
    try {
      await api.agents.remove(deleteAgent.id);
      pushToast(`${deleteAgent.name} deleted`);
      setDeleteAgent(null); result.reload();
    } catch (error) {
      setDeleteError(error instanceof Error ? error.message : 'Could not delete this agent. Please try again.');
    } finally { setDeleting(false); }
  };
  if (result.loading && !result.data) return <PageLoader />;
  return <div className="page agents-page">
    <div className="page-heading page-heading--split"><div><h2>AI agents</h2><p>Create focused experts, give each one a clear purpose, train them on trusted content, and deploy anywhere.</p></div><Button icon={Plus} onClick={() => setCreateOpen(true)}>Create agent</Button></div>
    <div className="list-toolbar"><div className="search-box"><Search /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search agents…" aria-label="Search agents" /></div><div className="view-toggle" role="group" aria-label="View style"><button className={view === 'grid' ? 'is-active' : ''} onClick={() => setView('grid')} aria-label="Grid view"><LayoutGrid /></button><button className={view === 'list' ? 'is-active' : ''} onClick={() => setView('list')} aria-label="List view"><List /></button></div></div>
    {filtered.length ? <div className={`agent-cards agent-cards--${view}`}>{filtered.map((agent) => <AgentCard key={agent.id} agent={agent} onSaved={result.reload} onDuplicate={() => setDuplicateAgent(agent)} onPurpose={() => setPurposeAgent(agent)} onDelete={() => setDeleteAgent(agent)} />)}</div> : <Card><EmptyState icon={Bot} title={search ? 'No matching agents' : 'Create your first agent'} description={search ? 'Try a different search term.' : 'Start with a focused job and teach your agent from trusted sources.'} action={!search ? <Button icon={Plus} onClick={() => setCreateOpen(true)}>Create agent</Button> : undefined} /></Card>}
    {createOpen ? <CreateAgentModal onClose={() => setCreateOpen(false)} onCreated={(agent) => { setCreateOpen(false); result.reload(); pushToast(agent.purpose === 'education' ? 'Education agent created in draft for safe provisioning' : 'Agent created'); navigate(`/agents/${agent.id}/instructions`); }} /> : null}
    {duplicateAgent ? <DuplicateAgentModal key={duplicateAgent.id} source={duplicateAgent} onClose={() => setDuplicateAgent(null)} onCreated={(agent) => { setDuplicateAgent(null); result.reload(); pushToast('Agent duplicated with its complete purpose and template'); navigate(`/agents/${agent.id}/instructions`); }} /> : null}
    {purposeAgent ? <PurposeModal key={purposeAgent.id} source={purposeAgent} onClose={() => setPurposeAgent(null)} onSaved={(agent) => { setPurposeAgent(null); result.reload(); pushToast(agent.purpose === 'education' ? 'Purpose changed to Education; agent moved to draft until education access is configured' : `Purpose changed to ${purposeLabels[agentPurpose(agent)]}`); }} /> : null}
    <Modal open={Boolean(deleteAgent)} onClose={closeDelete} title="Delete this agent?" description="This removes the agent and revokes its pending, active, and suspended student enrollments. Conversation history is retained." size="sm" footer={<><Button variant="secondary" disabled={deleting} onClick={closeDelete}>Cancel</Button><Button variant="danger" icon={Trash2} disabled={deleting} onClick={() => void remove()}>{deleting ? 'Deleting?' : 'Delete agent'}</Button></>}>{deleteError ? <div className="form-error" role="alert">{deleteError}</div> : null}<div className="confirm-agent"><span className="agent-avatar" style={{ background: deleteAgent?.appearance.primaryColor }}>{deleteAgent?.avatar}</span><div><strong>{deleteAgent?.name}</strong><small>{deleteAgent ? purposeLabels[agentPurpose(deleteAgent)] : ''} · {deleteAgent?.knowledgeCount} knowledge sources · {deleteAgent?.conversations} conversations</small></div></div></Modal>
  </div>;
}

function AgentCard({ agent, onSaved, onDuplicate, onPurpose, onDelete }: { agent: Agent; onSaved: () => void; onDuplicate: () => void; onPurpose: () => void; onDelete: () => void }) {
  const [open, setOpen] = useState(false); const ref = useRef<HTMLDivElement>(null);
  const [statusError, setStatusError] = useState('');
  useEffect(() => { const close = (event: MouseEvent) => { if (!ref.current?.contains(event.target as Node)) setOpen(false); }; document.addEventListener('mousedown', close); return () => document.removeEventListener('mousedown', close); }, []);
  const purpose = agentPurpose(agent);
  return <Card className="agent-card">
    <div className="agent-card__top"><span className="agent-avatar agent-avatar--lg" style={{ background: agent.appearance.primaryColor }}>{agent.avatar}</span><AgentStatusControl agent={agent} onSaved={onSaved} compact showEnrollmentLink={false} onError={setStatusError} /><Badge tone={purpose === 'lead_generation' ? 'brand' : purpose === 'education' ? 'purple' : 'neutral'}>{purposeLabels[purpose]}</Badge><div className="more-menu" ref={ref}><button className="icon-button" onClick={() => setOpen((value) => !value)} aria-label={`Actions for ${agent.name}`}><MoreHorizontal /></button>{open ? <div className="menu-popover"><button onClick={() => { setOpen(false); onPurpose(); }}><Sparkles />Change purpose</button><button onClick={() => { setOpen(false); onDuplicate(); }}><Copy />Duplicate</button><button className="danger" onClick={() => { setOpen(false); onDelete(); }}><Trash2 />Delete</button></div> : null}</div></div>
    {statusError ? <div className="form-error" role="alert">{statusError}</div> : null}
    <Link to={`/agents/${agent.id}/instructions`} className="agent-card__link"><h3>{agent.name}</h3><p>{agent.description}</p></Link>
    <p><strong>WhatsApp:</strong> {agent.whatsappNumber || 'No number assigned'}</p><div className="agent-card__stats"><span><strong>{formatCompact(agent.conversations)}</strong><small>Conversations</small></span><span><strong>{agent.resolutionRate}%</strong><small>Resolved</small></span><span><strong>{agent.knowledgeCount}</strong><small>Sources</small></span></div>
    {purpose === 'education' ? <Link className="button button--secondary button--sm agent-card__enrollments" to={`/education/enrollments?agentId=${agent.id}`}>Manage enrollments</Link> : null}
    <div className="agent-card__footer"><span>Updated {relativeTime(agent.lastUpdated)}</span><Link to={`/agents/${agent.id}/instructions`}>Open <Ellipsis /></Link></div>
  </Card>;
}

function PurposeModal({ source, onClose, onSaved }: { source: Agent; onClose: () => void; onSaved: (agent: Agent) => void }) {
  const [purpose, setPurpose] = useState<AgentPurpose>(() => agentPurpose(source)); const [saving, setSaving] = useState(false); const [error, setError] = useState('');
  const submit = async (event?: FormEvent) => { event?.preventDefault(); if (saving) return; setSaving(true); setError(''); try { onSaved(await api.agents.update(source.id, { purpose })); } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not change this agent purpose.'); } finally { setSaving(false); } };
  return <Modal open onClose={onClose} title="Change agent purpose" description="Purpose controls which business workflow this agent is allowed to enter." size="lg" footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button icon={Check} disabled={saving || purpose === agentPurpose(source)} onClick={() => void submit()}>{saving ? 'Saving…' : 'Save purpose'}</Button></>}>
    <form onSubmit={(event) => void submit(event)}><fieldset className="template-field"><legend>Agent purpose</legend><div className="template-grid">{purposeOptions.map(({ id, icon: Icon, name, description }) => <label key={id} className={purpose === id ? 'is-selected' : ''}><input type="radio" name="agent-purpose" value={id} checked={purpose === id} onChange={() => setPurpose(id)} /><Icon /><strong>{name}</strong><small>{description}</small></label>)}</div></fieldset>
      {purpose === 'education' ? <div className="hint-card"><BookOpen /><div><strong>Education agents stay in draft during provisioning</strong><p>They cannot be activated until Course, Batch, Student, and Enrollment authorization is configured. This prevents private course knowledge from using the general runtime.</p></div></div> : null}
      {error ? <div className="form-error" role="alert">{error}</div> : null}
    </form>
  </Modal>;
}

function DuplicateAgentModal({ source, onClose, onCreated }: { source: Agent; onClose: () => void; onCreated: (agent: Agent) => void }) {
  const [name, setName] = useState(() => `${source.name} copy`); const [deploymentChannel, setDeploymentChannel] = useState<DeploymentChannel>(() => source.appearance.deploymentChannel ?? 'website'); const [saving, setSaving] = useState(false); const [error, setError] = useState('');
  const submit = async (event?: FormEvent) => { event?.preventDefault(); if (!name.trim() || saving) return; setSaving(true); setError(''); try { onCreated(await api.agents.duplicate(source.id, { name: name.trim(), deploymentChannel })); } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not duplicate this agent.'); } finally { setSaving(false); } };
  return <Modal open onClose={onClose} title="Duplicate AI agent" description="Copy the complete bot template, including its purpose, and choose where this version will be deployed." size="lg" footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button icon={Copy} disabled={!name.trim() || saving} onClick={() => void submit()}>{saving ? 'Duplicating...' : 'Duplicate agent'}</Button></>}>
    <form onSubmit={(event) => void submit(event)}><Field label="Duplicate name" htmlFor="duplicate-agent-name"><input id="duplicate-agent-name" value={name} onChange={(event) => setName(event.target.value)} maxLength={120} autoFocus /></Field>
      <p><strong>Purpose:</strong> {purposeLabels[agentPurpose(source)]}</p>
      <fieldset className="deployment-option-field"><legend>Where do you want to add this bot?</legend><p>The matching channel template will appear in the agent workspace and Deploy preview.</p><div className="deployment-option-grid">{deploymentOptions.map(({ id, icon: Icon, name: optionName, description }) => <label key={id} className={deploymentChannel === id ? 'is-selected' : ''}><input type="radio" name="deployment-channel" value={id} checked={deploymentChannel === id} onChange={() => setDeploymentChannel(id)} /><Icon /><span><strong>{optionName}</strong><small>{description}</small></span></label>)}</div></fieldset>
      {error ? <div className="form-error" role="alert">{error}</div> : null}
    </form>
  </Modal>;
}

export function CreateAgentModal({ onClose, onCreated }: { onClose: () => void; onCreated: (agent: Agent) => void }) {
  const [step, setStep] = useState(0); const [name, setName] = useState(''); const [description, setDescription] = useState(''); const [purpose, setPurpose] = useState<AgentPurpose>('support'); const [tone, setTone] = useState<AgentTone>('friendly'); const [language, setLanguage] = useState('English'); const [deploymentChannel, setDeploymentChannel] = useState<DeploymentChannel>('website'); const [saving, setSaving] = useState(false); const [error, setError] = useState('');
  const [numbers, setNumbers] = useState<WhatsAppConnection[]>([]);
  const [numberId, setNumberId] = useState('');
  const [numberLoading, setNumberLoading] = useState(false);
  const [numberError, setNumberError] = useState('');
  const [numberRevision, setNumberRevision] = useState(0);
  const [agents, setAgents] = useState<Agent[]>([]);
  useEffect(() => {
    if (deploymentChannel !== 'whatsapp') return;
    let active = true;
    setNumberLoading(true); setNumberError('');
    void Promise.all([api.integrations.whatsapp.status(), api.agents.list()]).then(([status, items]) => {
      if (active) { setNumbers(status.connections ?? []); setAgents(items); }
    }).catch(() => { if (active) setNumberError('Could not load connected numbers. Check your integration access and retry.'); })
      .finally(() => { if (active) setNumberLoading(false); });
    return () => { active = false; };
  }, [deploymentChannel, numberRevision]);
  const selectedNumber = numbers.find((number) => number.id === numberId);
  const available = (number: WhatsAppConnection) => Boolean(number.id && !number.agentId && number.status === 'connected' && (!number.tokenExpiresAt || Date.parse(number.tokenExpiresAt) > Date.now()));
  const steps = ['Basics', 'Purpose', 'Voice', 'Channel'];
  const locale = getWidgetLocale(language);
  const canContinue = (step !== 0 || Boolean(name.trim())) && (step !== 3 || deploymentChannel !== 'whatsapp' || Boolean(!numberLoading && !numberError && selectedNumber && available(selectedNumber)));
  const submit = async () => { if (!name.trim()) return; setSaving(true); setError(''); try { const option = purposeOptions.find((item) => item.id === purpose)!; const created = await api.agents.create({ name: name.trim(), description: description.trim() || 'A helpful AI agent', purpose, template: option.template, tone, language, deploymentChannel, ...(deploymentChannel === 'whatsapp' ? { whatsappConnectionId: numberId } : {}) }); const saved = created.purpose === purpose ? created : await api.agents.update(created.id, { purpose }); onCreated(saved); } catch (reason) { const detail = reason instanceof ApiError && reason.detail && typeof reason.detail === 'object' ? (reason.detail as { error?: { message?: unknown }; detail?: unknown }).error?.message ?? (reason.detail as { detail?: unknown }).detail : null; setError(typeof detail === 'string' ? detail : reason instanceof Error ? reason.message : 'Could not create this agent.'); if (deploymentChannel === 'whatsapp') setNumberRevision((value) => value + 1); } finally { setSaving(false); } };
  const advance = () => { if (!canContinue || saving) return; if (step < steps.length - 1) { setStep((current) => current + 1); setError(''); } else void submit(); };
  return <Modal open onClose={onClose} title="Create an AI agent" description="Follow four simple steps. Purpose is saved as part of the agent and can be changed later." size="lg" footer={<><Button variant="secondary" onClick={step === 0 ? onClose : () => setStep((current) => current - 1)} icon={step === 0 ? undefined : ChevronLeft}>{step === 0 ? 'Cancel' : 'Back'}</Button><Button disabled={!canContinue || saving} icon={step === steps.length - 1 ? Check : ChevronRight} onClick={advance}>{saving ? 'Creating…' : step === steps.length - 1 ? 'Create agent' : 'Continue'}</Button></>}>
    <form className="agent-flow" onSubmit={(event) => { event.preventDefault(); advance(); }}>
      <ol className="agent-flow__steps" aria-label="Agent creation progress">{steps.map((label, index) => <li key={label} className={index === step ? 'is-active' : index < step ? 'is-complete' : ''}><span>{index < step ? <Check /> : index + 1}</span><small>{label}</small></li>)}</ol>
      {step === 0 ? <section className="agent-flow__panel"><div className="agent-flow__intro"><Sparkles /><div><h3>Let’s name your assistant</h3><p>Use a clear name so your team immediately knows what this bot does.</p></div></div><Field label="Agent name" htmlFor="agent-name"><input id="agent-name" value={name} onChange={(event) => setName(event.target.value)} placeholder="e.g. Product Guide" maxLength={64} autoFocus /></Field><Field label="What should it help with?" htmlFor="agent-description" hint="A short sentence is enough."><input id="agent-description" value={description} onChange={(event) => setDescription(event.target.value)} placeholder="e.g. Answer product and account questions" maxLength={120} /></Field></section> : null}
      {step === 1 ? <section className="agent-flow__panel"><div className="agent-flow__intro"><Bot /><div><h3>Choose its main purpose</h3><p>This is a real platform setting, not just a starter template. It determines which business workflow the agent can enter.</p></div></div><fieldset className="template-field"><legend>Agent purpose</legend><div className="template-grid">{purposeOptions.map(({ id, icon: Icon, name: purposeName, description: text }) => <label key={id} className={purpose === id ? 'is-selected' : ''}><input type="radio" name="purpose" value={id} checked={purpose === id} onChange={() => setPurpose(id)} /><Icon /><strong>{purposeName}</strong><small>{text}</small></label>)}</div></fieldset>{purpose === 'education' ? <div className="hint-card"><BookOpen /><div><strong>Safe education provisioning</strong><p>This Agent will be created as draft until Course, Batch, Student, and Enrollment access is configured.</p></div></div> : null}</section> : null}
      {step === 2 ? <section className="agent-flow__panel"><div className="agent-flow__intro"><MessageSquare /><div><h3>Choose how it communicates</h3><p>The language applies to labels, starter questions, typed conversations, and AI answers.</p></div></div><div className="two-fields"><Field label="Response tone" htmlFor="create-tone"><select id="create-tone" value={tone} onChange={(event) => setTone(event.target.value as AgentTone)}><option value="professional">Professional</option><option value="friendly">Friendly</option><option value="concise">Concise</option><option value="empathetic">Empathetic</option><option value="playful">Playful</option></select></Field><Field label="Primary language" htmlFor="create-language"><select id="create-language" value={language} onChange={(event) => setLanguage(event.target.value)}>{supportedWidgetLanguages.map((item) => <option key={item}>{item}</option>)}</select></Field></div><div className="agent-flow__language-preview" dir={language === 'Arabic' ? 'rtl' : 'ltr'}><small>Visitor preview</small><strong>{locale.welcomeTitle}</strong><span>{locale.suggestedQuestions[0]}</span></div></section> : null}
      {step === 3 ? <section className="agent-flow__panel"><div className="agent-flow__intro"><Globe2 /><div><h3>Where will people use this bot?</h3><p>Choose a channel now. The correct preview and deployment tools will be ready automatically.</p></div></div><fieldset className="deployment-option-field"><legend>Deployment channel</legend><div className="deployment-option-grid">{deploymentOptions.map(({ id, icon: Icon, name: optionName, description: text }) => <label key={id} className={deploymentChannel === id ? 'is-selected' : ''}><input type="radio" name="create-deployment-channel" value={id} checked={deploymentChannel === id} onChange={() => setDeploymentChannel(id)} /><Icon /><span><strong>{optionName}</strong><small>{text}</small></span></label>)}</div></fieldset>{deploymentChannel === 'telegram' ? <p>After creating your agent, open Deploy to connect your Telegram bot token and configure its webhook.</p> : null}{deploymentChannel === 'whatsapp' ? <div>
        <Field label="WhatsApp number for this bot" htmlFor="create-whatsapp-number" hint="Each number belongs to one bot. Manage existing assignments in Deploy.">
          <select id="create-whatsapp-number" value={numberId} disabled={numberLoading || saving} onChange={(event) => setNumberId(event.target.value)}>
            <option value="">{numberLoading ? 'Loading connected numbers?' : 'Select a connected number'}</option>
            {numbers.map((number) => <option key={number.id || number.phoneNumberId} value={number.id} disabled={!available(number)}>{number.displayPhoneNumber || number.phoneNumberId} ? {number.verifiedName}{number.agentId ? ` ? Assigned to ${agents.find((agent) => agent.id === number.agentId)?.name ?? 'another bot'}` : available(number) ? ' ? Available' : ' ? Connection setup needed'}</option>)}
          </select>
        </Field>
        {numberError ? <p role="alert">{numberError}</p> : null}
        {!numberLoading && !numbers.some(available) ? <p>No available connected numbers. Add a number in Integrations or release an existing assignment in Deploy.</p> : null}
        <div className="whatsapp-manager__actions"><a href="/integrations" target="_blank" rel="noreferrer">Manage WhatsApp numbers</a><Button variant="secondary" disabled={numberLoading || saving} onClick={() => setNumberRevision((value) => value + 1)}>Refresh numbers</Button></div>
        {purpose === 'education' ? <p>The number will be reserved for this draft bot. Replies start only after education access is configured and the bot is published.</p> : null}
      </div> : null}<div className="agent-flow__summary"><span><small>Agent</small><strong>{name}</strong></span><span><small>Purpose</small><strong>{purposeLabels[purpose]}</strong></span><span><small>Language</small><strong>{language}</strong></span><span><small>Channel</small><strong>{deploymentOptions.find((item) => item.id === deploymentChannel)?.name}</strong></span>{deploymentChannel === 'whatsapp' ? <span><small>WhatsApp number</small><strong>{selectedNumber?.displayPhoneNumber || selectedNumber?.phoneNumberId || 'Select a number'}</strong></span> : null}</div></section> : null}
      {error ? <div className="form-error" role="alert">{error}</div> : null}
    </form>
  </Modal>;
}
