import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { InteractiveChannelWorkspace } from '@/components/whatsapp-workspace-enhancer';
import { api } from '@/lib/api';
import { localizeAgentAppearance } from '@/lib/widget-localization';
import type { DeploymentChannel } from '@/types';

interface PreviewRuntimeState {
  target: HTMLElement | null;
  agentId: string | null;
  channel: DeploymentChannel | null;
  language: string | null;
}

const channelNames: Record<DeploymentChannel, string> = {
  website: 'Website',
  whatsapp: 'WhatsApp',
  telegram: 'Telegram',
  instagram: 'Instagram',
  facebook: 'Facebook Messenger',
  slack: 'Slack',
  teams: 'Microsoft Teams',
  api: 'Developer API',
  notion: 'Notion',
  zapier: 'Zapier',
};

const persistedLanguages = new Map<string, string>();
const persistedChannels = new Map<string, DeploymentChannel>();

function isChannel(value: string | null | undefined): value is DeploymentChannel {
  return Boolean(value && value in channelNames);
}

function findAgentId(): string | null {
  const builderSelect = document.querySelector<HTMLSelectElement>('select[aria-label="Select agent"]');
  if (builderSelect?.value) return builderSelect.value;

  const deploySelect = document.querySelector<HTMLSelectElement>('select[aria-label="Select deploy agent"]');
  if (deploySelect?.value) return deploySelect.value;

  const match = window.location.pathname.match(/\/agents\/([^/?#]+)/);
  return match?.[1] ? decodeURIComponent(match[1]) : null;
}

function findTarget(): HTMLElement | null {
  return document.querySelector<HTMLElement>('.agent-template-preview .deploy-preview__stage')
    ?? document.querySelector<HTMLElement>('.deploy-preview .deploy-preview__stage');
}

function channelFromFrame(target: HTMLElement): DeploymentChannel | null {
  const frame = target.querySelector<HTMLElement>('.channel-frame');
  if (!frame) return target.querySelector('.browser-mock') ? 'website' : null;
  if (frame.classList.contains('telegram-template')) return 'telegram';
  if (frame.classList.contains('whatsapp-template')) return 'whatsapp';
  if (frame.classList.contains('instagram-template')) return 'instagram';
  if (frame.classList.contains('messenger-template')) return 'facebook';
  for (const channel of ['telegram', 'slack', 'teams', 'api', 'notion', 'zapier'] as const) {
    if (frame.classList.contains(`generic-channel-template--${channel}`)) return channel;
  }
  return null;
}

function findChannel(target: HTMLElement | null): DeploymentChannel | null {
  const deploySelect = document.querySelector<HTMLSelectElement>('select[aria-label="Select deployment channel"]');
  if (target?.closest('.deploy-preview') && isChannel(deploySelect?.value)) return deploySelect.value;
  return target ? channelFromFrame(target) : null;
}

function findLanguage(): string | null {
  return document.querySelector<HTMLSelectElement>('.builder-editor select#language')?.value
    ?? document.querySelector<HTMLSelectElement>('select#ui-language')?.value
    ?? null;
}

async function persistLanguage(agentId: string, language: string): Promise<void> {
  if (persistedLanguages.get(agentId) === language) return;
  persistedLanguages.set(agentId, language);
  try {
    const agent = await api.agents.get(agentId);
    const currentLanguage = agent.appearance.interfaceLanguage ?? agent.language;
    if (agent.language === language && currentLanguage === language) return;
    await api.agents.update(agentId, {
      language,
      appearance: localizeAgentAppearance(agent.appearance, language),
    });
  } catch {
    persistedLanguages.delete(agentId);
  }
}

async function persistChannel(agentId: string, channel: DeploymentChannel): Promise<void> {
  if (persistedChannels.get(agentId) === channel) return;
  persistedChannels.set(agentId, channel);
  try {
    const agent = await api.agents.get(agentId);
    if ((agent.appearance.deploymentChannel ?? 'website') === channel) return;
    await api.agents.update(agentId, {
      appearance: { ...agent.appearance, deploymentChannel: channel },
    });
  } catch {
    persistedChannels.delete(agentId);
  }
}

export function ChannelPreviewRuntime() {
  const [state, setState] = useState<PreviewRuntimeState>({
    target: null,
    agentId: null,
    channel: null,
    language: null,
  });

  useEffect(() => {
    const sync = () => {
      const target = findTarget();
      const agentId = findAgentId();
      const channel = findChannel(target);
      const language = findLanguage();

      setState((current) => (
        current.target === target
        && current.agentId === agentId
        && current.channel === channel
        && current.language === language
          ? current
          : { target, agentId, channel, language }
      ));

      if (agentId && language) void persistLanguage(agentId, language);
      if (agentId && channel) void persistChannel(agentId, channel);
    };

    const onChange = (event: Event) => {
      if (!(event.target instanceof HTMLSelectElement)) return;
      const label = event.target.getAttribute('aria-label');
      if (
        event.target.id === 'language'
        || event.target.id === 'ui-language'
        || label === 'Select deployment channel'
        || label === 'Select agent'
        || label === 'Select deploy agent'
      ) {
        sync();
        queueMicrotask(sync);
      }
    };

    sync();
    const observer = new MutationObserver(sync);
    observer.observe(document.body, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ['class', 'value'],
    });
    document.addEventListener('change', onChange, true);
    window.addEventListener('popstate', sync);

    return () => {
      observer.disconnect();
      document.removeEventListener('change', onChange, true);
      window.removeEventListener('popstate', sync);
    };
  }, []);

  useEffect(() => {
    if (!state.target || state.channel === 'website') return;
    const previousPosition = state.target.style.position;
    state.target.style.position = 'relative';

    const toolbar = state.target.closest('.agent-template-preview')?.querySelector<HTMLElement>('.preview-toolbar span')
      ?? state.target.closest('.deploy-preview')?.querySelector<HTMLElement>('.preview-heading span');
    const previousText = toolbar?.textContent ?? '';
    if (toolbar && state.channel) toolbar.textContent = `${channelNames[state.channel]} preview`;

    return () => {
      state.target!.style.position = previousPosition;
      if (toolbar && previousText) toolbar.textContent = previousText;
    };
  }, [state.target, state.channel]);

  if (!state.target || !state.agentId || !state.channel || state.channel === 'website') return null;

  return createPortal(
    <InteractiveChannelWorkspace
      key={`${state.agentId}:${state.channel}:${state.language ?? 'English'}`}
      agentId={state.agentId}
      channel={state.channel}
      language={state.language ?? undefined}
    />,
    state.target,
  );
}
