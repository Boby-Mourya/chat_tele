import { Facebook, Instagram } from '@/components/social-icons';
import {
  Bot,
  Check,
  ChevronDown,
  Code2,
  Copy,
  Download,
  ExternalLink,
  FileCode2,
  Globe2,
  Image,
  Languages,
  Link2,
  MessageSquareText,
  Monitor,
  Paintbrush,
  PanelBottom,
  PlugZap,
  Plus,
  QrCode,
  RotateCcw,
  Save,
  ShieldCheck,
  SlidersHorizontal,
  Smartphone,
  Sparkles,
  ToggleRight,
  Type,
  WandSparkles,
  Workflow,
} from 'lucide-react';
import { useCallback, useEffect, useState, type CSSProperties, type ReactNode } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { ChatWidget } from '@/components/chat-widget';
import { IntegrationChatPreview } from '@/components/integration-chat-preview';
import { WhatsAppNumberDeployment } from '@/components/whatsapp-number-deployment';
import { WhatsAppMessageEditor, WhatsAppMessagePreview } from '@/components/whatsapp-message-editor';
import { useToast } from '@/components/providers';
import { Badge, Button, Card, EmptyState, Field, PageLoader, Switch } from '@/components/ui';
import { api } from '@/lib/api';
import { leadCrmApi, type TelegramBotInfo } from '@/lib/lead-crm-api';
import { TelegramStudentLink } from '@/components/telegram-setup-modal';
import { BotWorkflowBuilderPage } from '@/pages/BotWorkflowBuilderPage';
import { apiErrorMessage } from '@/lib/api-error-message';
import { createQrAssets, downloadQrAsset, type QrAssets } from '@/lib/qr';
import { useApi } from '@/lib/use-api';
import { getWidgetLocale, localizeAgentAppearance, supportedWidgetLanguages } from '@/lib/widget-localization';
import { validWhatsAppSettings, whatsappChatUrl } from '@/lib/whatsapp-messages';
import type { Agent, AgentAppearance, AgentPatch, DeploymentChannel, Integration, WhatsAppConnection } from '@/types';

const buildItems = [
  { id: 'source', label: 'Agent source', icon: Bot },
  { id: 'look', label: 'Look and feel', icon: Paintbrush },
  { id: 'toggle', label: 'Toggle', icon: ToggleRight },
  { id: 'starters', label: 'Conversation starters', icon: MessageSquareText },
  { id: 'color', label: 'Color studio', icon: WandSparkles },
  { id: 'font', label: 'Font studio', icon: Type },
  { id: 'greeting', label: 'Greeting editor', icon: Sparkles },
  { id: 'localization', label: 'Localization', icon: Languages },
  { id: 'gdpr', label: 'GDPR & consent', icon: ShieldCheck },
  { id: 'other', label: 'Other', icon: SlidersHorizontal },
] as const;

const shareItems = [
  { id: 'link', label: 'Get link', icon: Link2 },
  { id: 'qr', label: 'QR code', icon: QrCode },
  { id: 'embed', label: 'Instant embed', icon: Code2 },
  { id: 'iframe', label: 'IFrame embed', icon: FileCode2 },
] as const;

const whatsappBuildItems = [
  { id: 'channel', label: 'WhatsApp number', icon: PlugZap },
  { id: 'workflow', label: 'Workflow builder', icon: Workflow },
  { id: 'source', label: 'Agent source', icon: Bot },
  { id: 'activation', label: 'Bot activation', icon: ToggleRight },
  { id: 'welcome', label: 'Welcome message', icon: Sparkles },
  { id: 'format', label: 'Message format', icon: Type },
  { id: 'localization', label: 'Response language', icon: Languages },
] as const;

type DeploySection = (typeof buildItems)[number]['id'] | (typeof shareItems)[number]['id'] | (typeof whatsappBuildItems)[number]['id'];

const persistedSections = new Set<DeploySection>(['look', 'toggle', 'starters', 'color', 'font', 'greeting', 'localization', 'gdpr', 'other', 'link', 'channel', 'activation', 'welcome', 'format']);

function cloneAgent(agent: Agent): Agent {
  return {
    ...agent,
    appearance: { ...agent.appearance, suggestedQuestions: [...agent.appearance.suggestedQuestions], ...(agent.appearance.whatsapp ? { whatsapp: { ...agent.appearance.whatsapp } } : {}) },
    model: { ...agent.model },
    security: { ...agent.security, allowedDomains: [...agent.security.allowedDomains] },
  };
}

function savedDeployState(agent: Agent): Pick<Agent, 'status' | 'language' | 'appearance'> {
  return { status: agent.status, language: agent.language, appearance: agent.appearance };
}

function normalizeAppearance(appearance: AgentAppearance): AgentAppearance {
  return {
    ...appearance,
    primaryColor: appearance.primaryColor.toLowerCase(),
    suggestedQuestions: appearance.suggestedQuestions
      .map((question) => question.trim())
      .filter(Boolean)
      .slice(0, 8),
  };
}

function isValidAppearance(appearance: AgentAppearance): boolean {
  return /^#[0-9a-f]{6}$/i.test(appearance.primaryColor)
    && appearance.welcomeTitle.length <= 120
    && appearance.welcomeMessage.length <= 500
    && appearance.placeholder.length <= 120
    && appearance.suggestedQuestions.length <= 8;
}

export function DeployPage() {
  const [searchParams] = useSearchParams();
  const agents = useApi(() => api.agents.list());
  const integrations = useApi(() => api.integrations.list());
  const channelConnections = useApi(() => leadCrmApi.channelConnections());
  const [agentId, setAgentId] = useState(searchParams.get('agentId') || 'agent-northstar');
  const [integrationId, setIntegrationId] = useState('website');
  const [integrationOverrides, setIntegrationOverrides] = useState<Record<string, boolean>>({});
  const [savedAgents, setSavedAgents] = useState<Agent[]>([]);
  const [draftAgents, setDraftAgents] = useState<Agent[]>([]);
  const [section, setSection] = useState<DeploySection>('look');
  const [device, setDevice] = useState<'desktop' | 'mobile'>('mobile');
  const [saving, setSaving] = useState(false);
  const { pushToast } = useToast();

  useEffect(() => {
    if (!agents.data?.length) return;
    const next = agents.data.map(cloneAgent);
    setSavedAgents(next);
    setDraftAgents(next.map(cloneAgent));
    setAgentId((current) => next.some((agent) => agent.id === current) ? current : next[0]!.id);
  }, [agents.data]);

  const agent = draftAgents.find((item) => item.id === agentId) ?? draftAgents[0];
  const savedAgent = savedAgents.find((item) => item.id === agent?.id);
  const dirty = Boolean(agent && savedAgent && JSON.stringify(savedDeployState(agent)) !== JSON.stringify(savedDeployState(savedAgent)));
  const valid = Boolean(agent && isValidAppearance(agent.appearance) && validWhatsAppSettings(agent.appearance.whatsapp));
  const integration = integrations.data?.find((item) => item.id === integrationId) ?? integrations.data?.[0];
  const isWhatsApp = integration?.id === 'whatsapp';
  const visibleBuildItems = isWhatsApp ? whatsappBuildItems : buildItems;
  const visibleShareItems = isWhatsApp ? shareItems.filter((item) => item.id === 'link' || item.id === 'qr') : shareItems;
  const activeSection = isWhatsApp && ![...whatsappBuildItems, ...visibleShareItems].some((item) => item.id === section) ? 'channel' : section;
  const showActions = dirty || (persistedSections.has(activeSection) && !(isWhatsApp && activeSection === 'link'));
  const selectedAgentId = agent?.id;
  const preferredDeploymentChannel = agent?.appearance.deploymentChannel ?? 'website';

  useEffect(() => {
    if (!selectedAgentId) return;
    if (!integrations.data?.some((item) => item.id === preferredDeploymentChannel)) return;
    setIntegrationId(preferredDeploymentChannel);
    setSection(preferredDeploymentChannel === 'website' ? 'look' : 'channel');
  }, [selectedAgentId, preferredDeploymentChannel, integrations.data]);

  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ''; };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [dirty]);

  const numbersLoaded = useCallback((numbers: WhatsAppConnection[]) => {
    const refresh = (items: Agent[]) => items.map((item) => ({ ...item, whatsappNumber: numbers.find((number) => number.agentId === item.id)?.displayPhoneNumber || null }));
    setSavedAgents(refresh);
    setDraftAgents(refresh);
  }, []);

  const updateAgent = (patch: AgentPatch) => {
    if (!agent) return;
    setDraftAgents((current) => current.map((item) => item.id === agent.id ? { ...item, ...patch } : item));
  };

  const updateAppearance = (patch: Partial<AgentAppearance>) => {
    if (!agent) return;
    updateAgent({ appearance: { ...agent.appearance, ...patch } });
  };

  const reset = () => {
    if (!agent || !savedAgent) return;
    if (!dirty) {
      pushToast('There are no pending changes to reset', 'info');
      return;
    }
    setDraftAgents((current) => current.map((item) => item.id === agent.id ? cloneAgent(savedAgent) : item));
    pushToast(isWhatsApp ? 'WhatsApp changes reset' : 'Widget changes reset', 'info');
  };

  const save = async () => {
    if (!agent || !valid || saving) return;
    if (!dirty) {
      pushToast('All changes are already applied', 'info');
      return;
    }
    setSaving(true);
    try {
      const saved = await api.agents.update(agent.id, {
        appearance: normalizeAppearance(agent.appearance),
        ...(agent.status !== savedAgent?.status ? { status: agent.status } : {}),
        ...(agent.language !== savedAgent?.language ? { language: agent.language } : {}),
      });
      const next = cloneAgent(saved);
      setSavedAgents((current) => current.map((item) => item.id === saved.id ? next : item));
      setDraftAgents((current) => current.map((item) => item.id === saved.id ? cloneAgent(next) : item));
      pushToast(isWhatsApp ? 'WhatsApp settings applied' : 'Widget changes published');
    } catch (reason) {
      pushToast(apiErrorMessage(reason, 'Could not apply deployment changes'), 'error');
    } finally {
      setSaving(false);
    }
  };

  const setIntegrationConnected = async (item: Integration, connected: boolean) => {
    try {
      const saved = await api.integrations.setConnected(item.id, connected);
      setIntegrationOverrides((current) => ({ ...current, [item.id]: saved.connected }));
      pushToast(`${item.name} ${saved.connected ? 'enabled' : 'disabled'} for this workspace`);
    } catch (reason) {
      pushToast(reason instanceof Error ? reason.message : `Could not update ${item.name}`, 'error');
    }
  };

  if (agents.error || integrations.error) return <div className="page"><Card><EmptyState icon={PlugZap} title="Could not load deployment settings" description={agents.error || integrations.error || ''} action={<Button onClick={() => { agents.reload(); integrations.reload(); }}>Retry</Button>} /></Card></div>;
  if (agents.loading || integrations.loading) return <PageLoader />;
  if (!agents.data?.length) return <div className="page"><Card><EmptyState icon={Bot} title="Create a bot to get started" description="Your bot's deployment settings will appear here." action={<Link className="button button--primary" to="/agents">Go to agents</Link>} /></Card></div>;
  if (!agent) return <PageLoader />;

  const assignedNumberChanged = (number: string | null, previousAgentId?: string | null) => {
    const refresh = (items: Agent[]) => items.map((item) => item.id === agent.id ? { ...item, whatsappNumber: number } : item.id === previousAgentId ? { ...item, whatsappNumber: null } : item);
    setSavedAgents(refresh);
    setDraftAgents(refresh);
  };

  return <div className={`deploy-page${isWhatsApp ? ' deploy-page--whatsapp' : ''}`}>
    {integrationId === 'telegram' && <Card><h3>Telegram student access</h3><TelegramStudentLink bot={channelConnections.data?.find(connection => connection.provider === 'telegram' && connection.agent_id === agent.id && connection.status === 'healthy')?.configuration.telegram as TelegramBotInfo | undefined} /><Link to="/integrations?provider=telegram">Connect or manage Telegram</Link></Card>}
    <aside className="deploy-sidebar">
      <label className="deploy-sidebar__heading">
        <span className="agent-avatar" style={{ background: agent.appearance.primaryColor }}>{agent.avatar}</span>
        <span><small>Agent</small><strong>{agent.name}</strong></span>
        <select aria-label="Select deploy agent" disabled={saving} value={agent.id} onChange={(event) => setAgentId(event.target.value)}>
          {draftAgents.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select>
        <ChevronDown />
      </label>
      <label className="deploy-channel-select">
        <span><PlugZap /><small>Deployment channel</small><strong>{integration?.name ?? 'Website widget'}</strong></span>
        <select aria-label="Select deployment channel" disabled={saving} value={integration?.id ?? 'website'} onChange={(event) => { const channel = event.target.value as DeploymentChannel; setIntegrationId(channel); updateAgent({ appearance: { ...agent.appearance, deploymentChannel: channel }, ...(channel === 'whatsapp' && agent.appearance.deploymentChannel !== 'whatsapp' ? { status: 'draft' } : {}) }); setSection(channel === 'website' ? 'look' : 'channel'); }}>
          {integrations.data?.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select>
        <ChevronDown />
      </label>
      <p>BUILD</p>
      {visibleBuildItems.map(({ id, label, icon: Icon }) => <button key={id} className={activeSection === id ? 'is-active' : ''} onClick={() => setSection(id)}><Icon /><span>{label}</span></button>)}
      <p>SHARE</p>
      {visibleShareItems.map(({ id, label, icon: Icon }) => <button key={id} className={activeSection === id ? 'is-active' : ''} onClick={() => setSection(id)}><Icon /><span>{label}</span></button>)}
    </aside>

    <section className="deploy-editor">
      <div className="deploy-editor__heading">
        <div>
          <span className="page-kicker">{isWhatsApp ? 'WhatsApp bot settings' : 'Widget manager'}</span>
          <h2>{activeSection === 'channel' ? integration?.name : [...visibleBuildItems, ...visibleShareItems].find((item) => item.id === activeSection)?.label}</h2>
          <p>{isWhatsApp ? 'Set up your number and the messages your bot sends on WhatsApp.' : 'Customize and publish a polished experience for every visitor.'}</p>
        </div>
        {showActions ? <div className="deploy-heading-actions">
          <Button variant="ghost" icon={RotateCcw} disabled={saving} onClick={reset}>Reset changes</Button>
          <Button icon={Save} disabled={saving || !valid} onClick={() => void save()}>{saving ? 'Applying...' : 'Apply'}</Button>
        </div> : null}
      </div>
      {dirty ? <p className="wa-editor-note" role="status">You have unapplied changes for {agent.name}.</p> : null}
      {!valid ? <p className="wa-editor-validation" role="alert">Check the welcome message and reply structure before applying changes, or reset to your saved settings.</p> : null}
      <fieldset className="deploy-controls" disabled={saving} aria-label="Deployment settings">
      <DeployEditor
        key={agent.id}
        section={activeSection}
        agent={agent}
        agents={draftAgents}
        setAgentId={setAgentId}
        updateAgent={updateAgent}
        updateAppearance={updateAppearance}
        integration={integration}
        integrationConnected={integration ? integrationOverrides[integration.id] ?? integration.connected : false}
        setIntegrationConnected={setIntegrationConnected}
        setSection={setSection}
        onSave={save}
        onNumberChanged={assignedNumberChanged}
        onNumbersLoaded={numbersLoaded}
      />
      </fieldset>
    </section>

    <aside className="deploy-preview">
      <div className="preview-heading">
        <span><i className="status-dot status-dot--success" /> {integration?.name ?? 'Website widget'} preview</span>
        <div className="device-toggle">
          <button className={device === 'desktop' ? 'is-active' : ''} onClick={() => setDevice('desktop')} aria-label="Desktop preview"><Monitor /></button>
          <button className={device === 'mobile' ? 'is-active' : ''} onClick={() => setDevice('mobile')} aria-label="Mobile preview"><Smartphone /></button>
        </div>
      </div>
      <div className={`deploy-preview__stage deploy-preview__stage--${device}`}>
        <DeploymentPreview agent={agent} integrationId={integration?.id ?? 'website'} device={device} section={activeSection} />
      </div>
      <p className="preview-note">{isWhatsApp ? 'Message formatting preview. WhatsApp controls its own interface. Apply changes to use them in new replies.' : device === 'desktop' ? 'Desktop preview scales to fit the available canvas.' : 'Mobile preview uses the compact channel layout.'}</p>
    </aside>
  </div>;
}

function DeploymentPreview({ agent, integrationId, device, section }: { agent: Agent; integrationId: string; device: 'desktop' | 'mobile'; section: DeploySection }) {
  if (integrationId === 'whatsapp') return <WhatsAppMessagePreview agent={agent} device={device} showReply={section === 'format'} />;
  if (integrationId === 'website') return <WebsiteDeploymentPreview agent={agent} device={device} section={section} />;
  return <IntegrationChatPreview agent={agent} integrationId={integrationId} device={device} />;
}

export function AgentDeploymentPreview({ agent, integrationId, device = 'mobile' }: { agent: Agent; integrationId: string; device?: 'desktop' | 'mobile' }) {
  return <DeploymentPreview agent={agent} integrationId={integrationId} device={device} section="look" />;
}

function WebsiteDeploymentPreview({ agent, device, section }: { agent: Agent; device: 'desktop' | 'mobile'; section: DeploySection }) {
  const openOnLoad = agent.appearance.openOnPageLoad ?? false;
  const [manuallyOpen, setManuallyOpen] = useState(false);
  useEffect(() => { setManuallyOpen(false); }, [agent.id, agent.status, openOnLoad, section, device]);
  const enabled = agent.status === 'active';
  const showLauncherState = enabled && section === 'toggle' && !openOnLoad && !manuallyOpen;
  const width = agent.appearance.widgetWidth ?? 380;
  const height = agent.appearance.widgetHeight ?? 680;
  const previewWidth = device === 'desktop' ? (section === 'look' ? Math.min(542, Math.max(320, width)) : 542) : width;
  const previewHeight = device === 'desktop' ? Math.min(558, Math.max(500, height)) : height;
  const offset = device === 'desktop' ? 14 : 0;
  const side = agent.appearance.position === 'bottom-left' ? 'left' : 'right';
  const widgetStyle: CSSProperties = device === 'desktop' ? {
    width: 'calc(100% - 28px)',
    maxWidth: previewWidth,
    height: 'calc(100% - 60px)',
    maxHeight: previewHeight,
    bottom: offset,
    [side]: offset,
    transform: 'none',
    filter: agent.appearance.elevatedShadow === false ? 'none' : undefined,
  } : {};
  const LauncherIcon = agent.appearance.launcherStyle === 'bubble' ? MessageSquareText : Sparkles;
  const locale = getWidgetLocale(agent.appearance.interfaceLanguage);
  const previewAgent = section === 'localization' ? { ...agent, appearance: { ...agent.appearance, welcomeTitle: locale.welcomeTitle, welcomeMessage: locale.welcomeMessage, placeholder: locale.placeholder, suggestedQuestions: locale.suggestedQuestions } } : agent;

  return <div className="browser-mock" aria-label={`${device === 'desktop' ? 'Desktop' : 'Mobile'} website preview`}>
    <div className="browser-mock__bar"><i /><i /><i /><span>{agent.appearance.customDomain || 'yourwebsite.com'}</span></div>
    <div className="browser-mock__page"><div className="mock-nav" /><div className="mock-hero"><i /><i /><i /></div><div className="mock-cards"><i /><i /><i /></div></div>
    {!enabled ? <div className="preview-disabled-state"><ToggleRight /><strong>Widget disabled</strong><small>Turn on “Widget enabled” to show the launcher.</small></div> : showLauncherState ? <div className={`preview-launcher-state preview-launcher-state--${side}`} style={{ bottom: offset || 18, [side]: offset || 18 }}>
      <span>Launcher preview · click to open</span>
      <button type="button" className="preview-launcher" style={{ background: agent.appearance.primaryColor }} onClick={() => setManuallyOpen(true)} aria-label={`Preview ${agent.appearance.launcherStyle} launcher`}>
        {agent.appearance.launcherStyle === 'avatar' ? <span>{agent.avatar.slice(0, 2)}</span> : <LauncherIcon />}
      </button>
    </div> : <div className={`embedded-widget embedded-widget--${agent.appearance.position}`} style={widgetStyle}>
      {!openOnLoad && manuallyOpen ? <button type="button" className="preview-widget-close" onClick={() => setManuallyOpen(false)} aria-label="Close preview widget">&times;</button> : null}
      <ChatWidget key={agent.appearance.interfaceLanguage ?? 'English'} agent={previewAgent} embedded />
    </div>}
  </div>;
}

interface DeployEditorProps {
  section: DeploySection;
  agent: Agent;
  agents: Agent[];
  setAgentId: (id: string) => void;
  updateAgent: (patch: AgentPatch) => void;
  updateAppearance: (patch: Partial<AgentAppearance>) => void;
  integration?: Integration;
  integrationConnected: boolean;
  setIntegrationConnected: (integration: Integration, connected: boolean) => Promise<void>;
  setSection: (section: DeploySection) => void;
  onSave: () => Promise<void>;
  onNumberChanged: (number: string | null, previousAgentId?: string | null) => void;
  onNumbersLoaded: (numbers: WhatsAppConnection[]) => void;
}

function DeployEditor({ section, agent, agents, setAgentId, updateAgent, updateAppearance, integration, integrationConnected, setIntegrationConnected, setSection, onSave, onNumberChanged, onNumbersLoaded }: DeployEditorProps) {
  const [iframeWidth, setIframeWidth] = useState(100);
  const [iframeHeight, setIframeHeight] = useState(700);
  const [diagnostics, setDiagnostics] = useState('');
  const { pushToast } = useToast();
  const hostedUrl = `${window.location.origin}/demo/${agent.publicId}`;
  const embeddedUrl = `${window.location.origin}/widget/${agent.publicId}`;

  if (integration?.id === 'whatsapp') {
    if (section === 'workflow') return <div className="deploy-workflow-builder"><BotWorkflowBuilderPage key={agent.id} initialAgentId={agent.id} /></div>;
    if (section === 'welcome' || section === 'format') return <WhatsAppMessageEditor agent={agent} section={section} onChange={updateAppearance} />;
    if (section === 'activation') return <Panel title="Bot activation" description="Choose whether this bot responds to incoming WhatsApp messages."><Switch label="Bot active" checked={agent.status === 'active'} onChange={(active) => updateAgent({ status: active ? 'active' : 'draft' })} description="Active bots reply on their assigned number. Inactive bots stay in draft." /><p className="wa-editor-note">Apply changes to update the bot. A connected number is required; education bots also need their course and enrollment setup.</p></Panel>;
    if (section === 'localization') return <Panel title="Response language" description="Choose the language for generated answers. Write your welcome message and reply structure in the language you want to send."><Field label="Response language" htmlFor="wa-response-language"><select id="wa-response-language" value={agent.language} onChange={(event) => updateAgent({ language: event.target.value })}>{supportedWidgetLanguages.map((language) => <option key={language}>{language}</option>)}</select></Field></Panel>;
    if (section === 'channel') return <WhatsAppNumberDeployment key={agent.id} agentId={agent.id} onNumberChanged={onNumberChanged} onNumbersLoaded={onNumbersLoaded} />;
    if (section === 'link' || section === 'qr') {
      const url = whatsappChatUrl(agent.whatsappNumber);
      if (!url) return <Panel title="Connect a WhatsApp number" description="Assign a connected phone number to create its WhatsApp chat link and QR code."><Button onClick={() => setSection('channel')}>Choose WhatsApp number</Button></Panel>;
      if (section === 'qr') return <QrSharePanel hostedUrl={url} agent={agent} whatsapp />;
      return <SharePanel icon={Link2} title="WhatsApp chat link" description="Customers can open WhatsApp and message the number assigned to this bot."><div className="share-url"><Link2 /><span>{url}</span><CopyAction value={url} /></div><div className="share-actions"><a className="button button--secondary" href={url} target="_blank" rel="noreferrer">Open WhatsApp <ExternalLink /></a></div></SharePanel>;
    }
  }
  if (section === 'channel' && integration) return <IntegrationDeployPanel
    integration={integration}
    connected={integrationConnected}
    onToggle={(connected) => setIntegrationConnected(integration, connected)}
    onWebsite={() => setSection('embed')}
  />;

  if (section === 'source') return <Panel title="Choose an agent" description="Replies use the selected agent's knowledge, behavior, and model.">
    <Field label="Agent source" htmlFor="deploy-agent">
      <select id="deploy-agent" value={agent.id} onChange={(event) => setAgentId(event.target.value)}>{agents.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select>
    </Field>
    <div className="selected-agent">
      <span className="agent-avatar" style={{ background: agent.appearance.primaryColor }}>{agent.avatar}</span>
      <span><strong>{agent.name}</strong><small>{agent.knowledgeCount} sources &middot; {agent.status}</small></span>
      <Badge tone="success">Selected</Badge>
    </div>
    <Link className="inline-link" to={`/agents/${agent.id}/instructions`}>Edit agent <ExternalLink /></Link>
  </Panel>;

  if (section === 'look') return <>
    <Panel title="Widget dimensions" description="Set the expanded size. Mobile automatically fills available width.">
      <div className="two-fields"><NumberField label="Width" value={agent.appearance.widgetWidth ?? 380} onChange={(widgetWidth) => updateAppearance({ widgetWidth })} suffix="px" min={320} max={600} /><NumberField label="Height" value={agent.appearance.widgetHeight ?? 680} onChange={(widgetHeight) => updateAppearance({ widgetHeight })} suffix="px" min={480} max={900} /></div>
      <div className="segmented-field"><span>Placement</span><div>
        <button className={agent.appearance.position === 'bottom-left' ? 'is-active' : ''} onClick={() => updateAppearance({ position: 'bottom-left' })}>Bottom left</button>
        <button className={agent.appearance.position === 'bottom-right' ? 'is-active' : ''} onClick={() => updateAppearance({ position: 'bottom-right' })}>Bottom right</button>
      </div></div>
      <div className="two-fields"><NumberField label="Page margin" value={agent.appearance.pageMargin ?? 24} onChange={(pageMargin) => updateAppearance({ pageMargin })} suffix="px" min={8} max={64} /><Field label="Text direction" htmlFor="direction"><select id="direction" value={agent.appearance.textDirection ?? 'ltr'} onChange={(event) => updateAppearance({ textDirection: event.target.value as 'ltr' | 'rtl' })}><option value="ltr">Left to right</option><option value="rtl">Right to left</option></select></Field></div>
      <Switch label="Elevated shadow" description="Separate the widget from page content." checked={agent.appearance.elevatedShadow ?? true} onChange={(elevatedShadow) => updateAppearance({ elevatedShadow })} />
    </Panel>
    <Panel title="Interface copy" description="Fine-tune high-visibility widget text.">
      <Field label="Hero heading" htmlFor="look-hero"><input id="look-hero" maxLength={120} value={agent.appearance.welcomeTitle} onChange={(event) => updateAppearance({ welcomeTitle: event.target.value })} /></Field>
      <Field label="Input placeholder" htmlFor="look-placeholder"><input id="look-placeholder" maxLength={120} value={agent.appearance.placeholder} onChange={(event) => updateAppearance({ placeholder: event.target.value })} /></Field>
      <Field label="AI warning" htmlFor="look-warning" hint="This safety disclosure is managed by the widget runtime."><input id="look-warning" value="AI can make mistakes. Check important information." disabled /></Field>
    </Panel>
  </>;

  if (section === 'toggle') return <Panel title="Launcher behavior" description="Control how and when the widget appears.">
    <Switch label="Widget enabled" description="Show the launcher on connected websites." checked={agent.status === 'active'} onChange={(enabled) => updateAgent({ status: enabled ? 'active' : 'draft' })} />
    <Switch label="Open on page load" description="Open the chat automatically when a visitor loads the page." checked={agent.appearance.openOnPageLoad ?? false} onChange={(openOnPageLoad) => updateAppearance({ openOnPageLoad })} />
    <div className="launcher-options"><strong>Launcher style</strong><div>
      <button className={agent.appearance.launcherStyle === 'spark' ? 'is-active' : ''} onClick={() => updateAppearance({ launcherStyle: 'spark' })}><Sparkles />Spark</button>
      <button className={agent.appearance.launcherStyle === 'bubble' ? 'is-active' : ''} onClick={() => updateAppearance({ launcherStyle: 'bubble' })}><MessageSquareText />Bubble</button>
      <button className={agent.appearance.launcherStyle === 'avatar' ? 'is-active' : ''} onClick={() => updateAppearance({ launcherStyle: 'avatar' })}><Image />Avatar</button>
    </div></div>
  </Panel>;

  if (section === 'starters') return <Panel title="Conversation starters" description="Help visitors begin with your most useful questions.">
    <div className="editable-list">{agent.appearance.suggestedQuestions.map((question, index) => <div key={index}>
      <span>{index + 1}</span>
      <input aria-label={`Conversation starter ${index + 1}`} maxLength={180} value={question} onChange={(event) => {
        const suggestedQuestions = [...agent.appearance.suggestedQuestions];
        suggestedQuestions[index] = event.target.value;
        updateAppearance({ suggestedQuestions });
      }} />
      <button aria-label={`Remove conversation starter ${index + 1}`} onClick={() => updateAppearance({ suggestedQuestions: agent.appearance.suggestedQuestions.filter((_, itemIndex) => itemIndex !== index) })}>&times;</button>
    </div>)}</div>
    <Button variant="secondary" icon={Plus} disabled={agent.appearance.suggestedQuestions.length >= 8} onClick={() => updateAppearance({ suggestedQuestions: [...agent.appearance.suggestedQuestions, ''] })}>Add starter</Button>
  </Panel>;

  if (section === 'color') {
    const colorValid = /^#[0-9a-f]{6}$/i.test(agent.appearance.primaryColor);
    return <Panel title="Color studio" description="Set an accessible palette that matches your brand.">
      <div className="palette-preview"><i style={{ background: colorValid ? agent.appearance.primaryColor : '#146cf6' }} /><i style={{ background: '#07111f' }} /><i style={{ background: '#f6f8fb' }} /><i style={{ background: '#ffffff' }} /></div>
      <Field label="Primary color" htmlFor="deploy-color" error={colorValid ? undefined : 'Enter a six-digit hex color, for example #146cf6.'}><div className="color-input">
        <input type="color" id="deploy-color" value={colorValid ? agent.appearance.primaryColor : '#146cf6'} onChange={(event) => updateAppearance({ primaryColor: event.target.value })} />
        <input aria-label="Primary color hex" value={agent.appearance.primaryColor} onChange={(event) => updateAppearance({ primaryColor: event.target.value })} />
      </div></Field>
      <div className="preset-colors">{['#146cf6', '#705cf6', '#0f9f84', '#e5484d', '#df6c1b', '#111827'].map((color) => <button key={color} style={{ background: color }} onClick={() => updateAppearance({ primaryColor: color })} aria-label={`Use color ${color}`} />)}</div>
      <div className="contrast-check"><Check /><span><strong>High contrast</strong><small>Button labels remain easy to read.</small></span></div>
    </Panel>;
  }

  if (section === 'font') return <Panel title="Font studio" description="Choose typography that feels native to your website.">
    <Field label="Font family" htmlFor="font-family"><select id="font-family" value={agent.appearance.fontFamily ?? 'Inter'} onChange={(event) => updateAppearance({ fontFamily: event.target.value as AgentAppearance['fontFamily'] })}><option>Inter</option><option>DM Sans</option><option>Manrope</option><option>System UI</option></select></Field>
    <NumberField label="Corner radius" value={agent.appearance.cornerRadius ?? 24} onChange={(cornerRadius) => updateAppearance({ cornerRadius })} suffix="px" min={0} max={32} />
    <div className="font-sample" style={{ fontFamily: agent.appearance.fontFamily ?? 'Inter', borderRadius: agent.appearance.cornerRadius ?? 24 }}><small>FONT PREVIEW</small><h3>{agent.appearance.welcomeTitle}</h3><p>{agent.appearance.welcomeMessage}</p><button style={{ background: agent.appearance.primaryColor }}>Start a conversation</button></div>
  </Panel>;

  if (section === 'greeting') return <Panel title="Greeting editor" description="Welcome visitors at the right moment without being intrusive.">
    <Field label="Greeting" htmlFor="greeting"><textarea id="greeting" rows={4} maxLength={500} value={agent.appearance.welcomeMessage} onChange={(event) => updateAppearance({ welcomeMessage: event.target.value })} /></Field>
    <fieldset className="greeting-modes"><legend>Show greeting</legend>{[['always', 'Always'], ['once', 'Once per session'], ['interaction', 'Until interaction'], ['never', 'Never']].map(([value, label]) => <label key={value} className={(agent.appearance.greetingMode ?? 'once') === value ? 'is-selected' : ''}>
      <input type="radio" name="greeting-mode" checked={(agent.appearance.greetingMode ?? 'once') === value} onChange={() => updateAppearance({ greetingMode: value as AgentAppearance['greetingMode'] })} />
      <span><strong>{label}</strong><small>{value === 'always' ? 'Every page load' : value === 'once' ? 'Once until the browser closes' : value === 'interaction' ? 'Until the visitor opens chat' : 'Launcher only'}</small></span>
    </label>)}</fieldset>
  </Panel>;

  if (section === 'localization') {
    const locale = getWidgetLocale(agent.appearance.interfaceLanguage);
    return <Panel title="Localization" description="Translate interface labels while the agent answers in the visitor's language.">
    <Field label="Interface language" htmlFor="ui-language"><select id="ui-language" value={agent.appearance.interfaceLanguage ?? agent.language ?? 'English'} onChange={(event) => { const language = event.target.value; updateAgent({ language, appearance: localizeAgentAppearance(agent.appearance, language) }); }}>{supportedWidgetLanguages.map((language) => <option key={language}>{language}</option>)}</select></Field>
    <div className="localization-fields">{([
      ['newConversation', 'New conversation', 'New conversation'],
      ['sendButton', 'Send button', 'Send'],
      ['closeChat', 'Close chat', 'Close chat'],
      ['offlineMessage', 'Offline message', "We'll be back soon"],
    ] as const).map(([key, label]) => <Field key={key} label={label}><input value={agent.appearance.translations?.[key] ?? locale.translations[key]} onChange={(event) => updateAppearance({ translations: { ...locale.translations, ...agent.appearance.translations, [key]: event.target.value } })} /></Field>)}</div>
    <Switch label="Detect browser language" description="Use a saved translation when one is available." checked={agent.appearance.detectBrowserLanguage ?? true} onChange={(detectBrowserLanguage) => updateAppearance({ detectBrowserLanguage })} />
  </Panel>;
  }

  if (section === 'gdpr') return <Panel title="GDPR & consent" description="Give visitors clear control before collecting personal data.">
    <Switch label="Require consent" description="Visitors must agree before starting a conversation." checked={agent.appearance.requireConsent ?? false} onChange={(requireConsent) => updateAppearance({ requireConsent })} />
    {agent.appearance.requireConsent ? <><Field label="Consent message" htmlFor="consent-message"><textarea id="consent-message" rows={4} maxLength={500} value={agent.appearance.consentMessage ?? 'I agree that my messages may be processed to answer my request.'} onChange={(event) => updateAppearance({ consentMessage: event.target.value })} /></Field><Field label="Privacy policy URL" htmlFor="privacy-url"><input id="privacy-url" type="url" value={agent.appearance.privacyPolicyUrl ?? ''} onChange={(event) => updateAppearance({ privacyPolicyUrl: event.target.value })} placeholder="https://example.com/privacy" /></Field></> : null}
    <div className="privacy-note"><ShieldCheck /><span><strong>Privacy by design</strong><small>Sensitive data masking and retention controls are configured on the agent.</small></span></div>
  </Panel>;

  if (section === 'other') return <Panel title="Advanced options" description="Fine-grained identity and display controls.">
    <Switch label="Northstar branding" description="Show Powered by Northstar AI below the composer." checked={agent.appearance.showBranding} onChange={(showBranding) => updateAppearance({ showBranding })} />
    <Field label="Internal widget name" htmlFor="widget-name"><input id="widget-name" maxLength={120} value={agent.appearance.widgetName ?? `${agent.name} widget`} onChange={(event) => updateAppearance({ widgetName: event.target.value })} /></Field>
    <NumberField label="Layer (z-index)" value={agent.appearance.zIndex ?? 99999} onChange={(zIndex) => updateAppearance({ zIndex })} min={1} max={2147483647} />
    <div className="readonly-field"><span><strong>Widget ID</strong><small>Immutable installation identifier</small></span><code>wdg_{agent.id.replace('agent-', '')}</code></div>
  </Panel>;

  if (section === 'link') return <SharePanel icon={Link2} title="Hosted widget link" description="Share a full-page version in emails, documents, or social posts.">
    <div className="share-url"><Globe2 /><span>{hostedUrl}</span><CopyAction value={hostedUrl} /></div>
    <div className="share-actions"><Link to={`/demo/${agent.publicId}`} target="_blank" rel="noreferrer"><Button icon={ExternalLink}>Open demo</Button></Link></div>
    <hr />
    <Field label="Custom domain" htmlFor="custom-domain" hint="Create a CNAME record after saving."><input id="custom-domain" value={agent.appearance.customDomain ?? ''} onChange={(event) => updateAppearance({ customDomain: event.target.value.trim().toLowerCase() })} placeholder="ask.yourcompany.com" /></Field>
    <Button variant="secondary" disabled={!agent.appearance.customDomain} onClick={() => void onSave()}>Save domain</Button>
  </SharePanel>;

  if (section === 'qr') return <QrSharePanel hostedUrl={hostedUrl} agent={agent} />;

  if (section === 'embed') {
    const code = `<script src="${window.location.origin}/widget.js" data-agent-id="${agent.publicId}" async></script>`;
    return <SharePanel icon={Code2} title="Instant embed" description="Paste this before the closing </body> tag on every page where chat should appear.">
      <CodeSnippet value={code} />
      <div className="connected-domains"><strong>Allowed domains</strong>{agent.security.allowedDomains.map((domain) => <span key={domain}><i className="status-dot status-dot--success" /> {domain} <Badge tone="success">Allowed</Badge></span>)}</div>
      <div className="recovery-tip"><PanelBottom /><span><strong>Widget not appearing?</strong><small>{diagnostics || 'Check the browser console, domain allowlist, and content security policy.'}</small></span><button onClick={() => {
        const host = window.location.hostname;
        const allowed = agent.security.allowedDomains.some((domain) => domain === host || host.endsWith(`.${domain}`));
        const result = agent.status !== 'active' ? 'Agent is disabled. Enable it under Toggle and apply changes.' : allowed ? `Checks passed for ${host}. The embed code and domain allowlist are valid.` : `${host} is not in this agent's allowed domains.`;
        setDiagnostics(result);
        pushToast(result, allowed && agent.status === 'active' ? 'success' : 'info');
      }}>Run diagnostics</button></div>
    </SharePanel>;
  }

  const iframe = `<iframe src="${embeddedUrl}" title="Chat with ${agent.name}" width="${iframeWidth}%" height="${iframeHeight}" frameborder="0" allow="clipboard-write"></iframe>`;
  return <SharePanel icon={FileCode2} title="IFrame embed" description="Place a complete chat experience inside a page, portal, or app.">
    <CodeSnippet value={iframe} />
    <div className="two-fields"><NumberField label="Width" value={iframeWidth} onChange={setIframeWidth} suffix="%" min={20} max={100} /><NumberField label="Height" value={iframeHeight} onChange={setIframeHeight} suffix="px" min={480} max={1200} /></div>
  </SharePanel>;
}

function QrSharePanel({ hostedUrl, agent, whatsapp = false }: { hostedUrl: string; agent: Agent; whatsapp?: boolean }) {
  const [assets, setAssets] = useState<QrAssets>();
  const [error, setError] = useState('');
  const { pushToast } = useToast();

  useEffect(() => {
    let active = true;
    setAssets(undefined);
    setError('');
    void createQrAssets(hostedUrl)
      .then((result) => { if (active) setAssets(result); })
      .catch(() => { if (active) setError('Could not generate this QR code. Please try again.'); });
    return () => { active = false; };
  }, [hostedUrl]);

  const download = (format: 'png' | 'svg') => {
    if (!assets) return;
    downloadQrAsset(assets, format, agent.publicId);
    pushToast(`QR code downloaded as ${format.toUpperCase()}`);
  };

  return <SharePanel icon={QrCode} title="QR code" description={whatsapp ? 'Scan to start a WhatsApp chat with this bot’s assigned number.' : 'Send visitors directly to your hosted agent from print or physical spaces.'}>
    <div className="qr-layout">
      <div className="qr-code-preview" aria-live="polite">
        {assets ? <img src={assets.pngDataUrl} alt={`QR code linking to ${hostedUrl}`} /> : <span>{error ? <QrCode /> : 'Generating...'}</span>}
      </div>
      <div>
        <strong>{error ? 'QR unavailable' : assets ? 'Ready to scan' : 'Preparing QR code'}</strong>
        <p>{error || 'High contrast with a quiet zone for reliable scanning.'}</p>
        <Button icon={Download} disabled={!assets} onClick={() => download('png')}>Download PNG</Button>
        <Button variant="secondary" icon={Download} disabled={!assets} onClick={() => download('svg')}>Download SVG</Button>
      </div>
    </div>
  </SharePanel>;
}

function IntegrationDeployPanel({ integration, connected, onToggle, onWebsite }: { integration: Integration; connected: boolean; onToggle: (connected: boolean) => Promise<void>; onWebsite: () => void }) {
  const [updating, setUpdating] = useState(false);
  const Icon = integration.id === 'facebook' ? Facebook : integration.id === 'instagram' ? Instagram : integration.id === 'website' ? Globe2 : integration.id === 'whatsapp' ? MessageSquareText : PlugZap;
  const toggle = async () => {
    setUpdating(true);
    try { await onToggle(!connected); } finally { setUpdating(false); }
  };

  return <SharePanel icon={Icon} title={integration.name} description={integration.description}>
    <div className="integration-deploy-status">
      <span className={`integration-deploy-status__icon ${connected ? 'is-connected' : ''}`}><Icon /></span>
      <span><strong>{connected ? 'Available in this workspace' : 'Not connected'}</strong><small>{connected ? 'This channel can use your selected agent.' : `Connect ${integration.name} to make it available for deployment.`}</small></span>
      {connected ? <Badge tone="success"><Check /> Connected</Badge> : null}
    </div>
    <div className="share-actions integration-deploy-actions">
      {integration.id === 'telegram' ? <Link to="/integrations?provider=telegram"><Button icon={ExternalLink}>Set up Telegram bot</Button></Link> : integration.id === 'website' ? <Button icon={Code2} onClick={onWebsite}>View embed options</Button> : integration.id === 'whatsapp' ? <Link to="/integrations"><Button icon={ExternalLink}>{connected ? 'Manage WhatsApp' : 'Connect WhatsApp'}</Button></Link> : <Button disabled={integration.comingSoon || updating} onClick={() => void toggle()}>{integration.comingSoon ? 'Coming soon' : updating ? 'Updating...' : connected ? 'Disable channel' : 'Enable channel'}</Button>}
      <Link to="/integrations"><Button variant="secondary">All integrations</Button></Link>
    </div>
  </SharePanel>;
}

function Panel({ title, description, children }: { title: string; description: string; children: ReactNode }) {
  return <Card className="deploy-panel"><div className="deploy-panel__heading"><h3>{title}</h3><p>{description}</p></div><div className="deploy-panel__body">{children}</div></Card>;
}

function SharePanel({ icon: Icon, title, description, children }: { icon: typeof Link2; title: string; description: string; children: ReactNode }) {
  return <Card className="share-panel"><div className="share-panel__hero"><span><Icon /></span><h3>{title}</h3><p>{description}</p></div><div className="share-panel__body">{children}</div></Card>;
}

function NumberField({ label, value, onChange, suffix, min, max }: { label: string; value: number; onChange: (value: number) => void; suffix?: string; min: number; max: number }) {
  return <Field label={label}><div className="number-field"><input type="number" value={value} min={min} max={max} onChange={(event) => onChange(Number(event.target.value))} />{suffix ? <span>{suffix}</span> : null}</div></Field>;
}

function CopyAction({ value }: { value: string }) {
  const [state, setState] = useState<'idle' | 'copied' | 'failed'>('idle');
  const copy = async () => {
    try {
      if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(value);
      else {
        const input = document.createElement('textarea');
        input.value = value; input.style.position = 'fixed'; input.style.opacity = '0';
        document.body.appendChild(input); input.select();
        if (!document.execCommand('copy')) throw new Error('Copy unavailable');
        input.remove();
      }
      setState('copied');
    } catch { setState('failed'); }
    window.setTimeout(() => setState('idle'), 1400);
  };
  return <button onClick={() => void copy()}>{state === 'copied' ? <Check /> : <Copy />}{state === 'copied' ? 'Copied' : state === 'failed' ? 'Copy failed' : 'Copy'}</button>;
}

function CodeSnippet({ value }: { value: string }) {
  return <div className="large-code"><pre><code>{value}</code></pre><CopyAction value={value} /></div>;
}
