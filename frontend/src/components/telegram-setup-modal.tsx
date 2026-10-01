import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { Button, Field, Modal } from '@/components/ui';
import { api } from '@/lib/api';
import { leadCrmApi, type ChannelConnectionView, type TelegramBotInfo, type TelegramProvisioningStatus } from '@/lib/lead-crm-api';
import { useApi } from '@/lib/use-api';

export function trustedTelegramUrl(value: string): boolean {
  try {
    const url = new URL(value);
    return url.protocol === 'https:' && url.hostname === 't.me' && !url.port && !url.username && !url.password
      && /^\/[A-Za-z0-9_]{5,32}$/.test(url.pathname) && !url.hash;
  } catch { return false; }
}

export function TelegramStudentLink({ bot }: { bot?: TelegramBotInfo | null }) {
  if (!bot || !trustedTelegramUrl(bot.studentUrl)) return null;
  return <div className="connection-details"><span>Bot</span><strong>{bot.botName}</strong><span>Username</span><strong>@{bot.botUsername}</strong><span>Student bot</span><a href={bot.studentUrl} target="_blank" rel="noopener noreferrer">{bot.studentUrl}</a></div>;
}

export function TelegramSetupModal({ connections, canManage, onClose, onChanged }: {
  connections: ChannelConnectionView[]; canManage: boolean; onClose: () => void; onChanged: () => void;
}) {
  const agents = useApi(() => api.agents.list());
  const available = (agents.data ?? []).filter(agent => agent.appearance.deploymentChannel === 'telegram');
  const [agentId, setAgentId] = useState(connections.find(c => c.provider === 'telegram')?.agent_id ?? '');
  const [selectedAccount, setSelectedAccount] = useState('');
  const [newAccountId, setNewAccountId] = useState('');
  const accounts = connections.filter(c => c.provider === 'telegram' && c.agent_id === agentId);
  const connection = newAccountId ? undefined : accounts.find(c => c.id === selectedAccount) ?? accounts[0];
  const [provisioning, setProvisioning] = useState<TelegramProvisioningStatus | null>(null);
  const [telegramUrl, setTelegramUrl] = useState('');
  const [busy, setBusy] = useState(false);
  const [disconnected, setDisconnected] = useState(false);
  const [error, setError] = useState('');
  const callbacks = useRef({ onChanged });
  callbacks.current = { onChanged };
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => { if (!agentId && available.length === 1 && available[0]) setAgentId(available[0].id); }, [agentId, available]);
  const waiting = !!provisioning && ['pending', 'awaiting_bot_creation', 'awaiting_confirmation', 'configuring'].includes(provisioning.status);
  const connected = !disconnected && (provisioning?.status === 'connected' || connection?.status === 'healthy');
  const connectionId = provisioning?.connectionId ?? connection?.id;
  const bot = provisioning?.bot ?? connection?.configuration.telegram as TelegramBotInfo | undefined;
  useEffect(() => {
    if (provisioning?.status === 'connected' && provisioning.connectionId) {
      setSelectedAccount(provisioning.connectionId);
      setNewAccountId('');
    }
  }, [provisioning?.status, provisioning?.connectionId]);

  useEffect(() => {
    if (!waiting || !provisioning) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const result = await leadCrmApi.getTelegramProvisioningStatus(provisioning.sessionId);
        if (cancelled) return;
        setProvisioning(result);
        if (result.status === 'connected') callbacks.current.onChanged();
        if (['failed', 'expired', 'cancelled'].includes(result.status)) setError(result.error || 'Connection expired. Click Connect to try again.');
        if (['pending', 'awaiting_bot_creation', 'awaiting_confirmation', 'configuring'].includes(result.status)) timer = setTimeout(() => void poll(), 2000);
      } catch (cause) {
        if (!cancelled) { setError(cause instanceof Error ? cause.message : 'Could not check Telegram connection.'); setProvisioning(null); }
      }
    };
    timer = setTimeout(() => void poll(), 1000);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [waiting, provisioning?.sessionId]);

  async function connect() {
    setBusy(true); setError(''); setDisconnected(false);
    // Open synchronously to avoid popup blocking while the authenticated API runs.
    const popup = window.open('about:blank', '_blank');
    if (popup) popup.opener = null;
    try {
      const result = newAccountId
        ? await leadCrmApi.startTelegramConnection(agentId, { accountId: newAccountId })
        : connection
          ? await leadCrmApi.startTelegramConnection(agentId, { connectionId: connection.id })
          : await leadCrmApi.startTelegramConnection(agentId);
      if (!mounted.current) { popup?.close(); return; }
      if (result.telegramUrl) {
        if (!trustedTelegramUrl(result.telegramUrl)) throw new Error('Invalid Telegram connection URL.');
        setTelegramUrl(result.telegramUrl);
        if (popup) popup.location.href = result.telegramUrl;
      } else popup?.close();
      setProvisioning(result);
      if (result.status === 'connected') callbacks.current.onChanged();
      if (result.status === 'failed') setError(result.error || 'Telegram connection failed. Try Connect again.');
    } catch (cause) {
      popup?.close();
      if (mounted.current) setError(cause instanceof Error ? cause.message : 'Could not connect Telegram.');
    } finally { if (mounted.current) setBusy(false); }
  }

  async function disconnect() {
    if (!connectionId) return;
    setBusy(true); setError('');
    try {
      await leadCrmApi.disconnectTelegramConnection(connectionId);
      if (!mounted.current) return;
      setProvisioning(null); setDisconnected(true); callbacks.current.onChanged();
    } catch (cause) { if (mounted.current) setError(cause instanceof Error ? cause.message : 'Could not disconnect Telegram.'); }
    finally { if (mounted.current) setBusy(false); }
  }

  return <Modal open title="Telegram" description="Connect your agent to Telegram." onClose={onClose} size="md" footer={
    connected || (!disconnected && connection?.status !== 'disabled' && connection && !bot?.managed && !waiting)
      ? <Button disabled={!canManage || busy} onClick={() => void disconnect()}>{busy ? 'Disconnecting…' : 'Disconnect'}</Button>
      : <Button disabled={!canManage || busy || waiting || !agentId} onClick={() => void connect()}>{busy || waiting ? 'Connecting…' : 'Connect'}</Button>
  }>
    <div className="connection-setup">
      <Field label="Agent" htmlFor="telegram-agent"><select id="telegram-agent" disabled={busy || waiting} value={agentId} onChange={event => { setAgentId(event.target.value); setSelectedAccount(''); setNewAccountId(''); setProvisioning(null); setTelegramUrl(''); setDisconnected(false); setError(''); }}><option value="">Select an agent</option>{available.map(agent => <option value={agent.id} key={agent.id}>{agent.name}</option>)}</select></Field>
      <section className="connection-app-fields" aria-label="Telegram accounts">
        <h3>Telegram accounts</h3>
        <p>Connect multiple bots to this agent. Each bot has its own student link and can be disconnected separately. Accounts are private to this workspace.</p>
        {!!accounts.length && <Field label="Bot account" htmlFor="telegram-account"><select id="telegram-account" disabled={busy || waiting} value={newAccountId ? 'new' : connection?.id ?? ''} onChange={event => { setSelectedAccount(event.target.value); setNewAccountId(''); setProvisioning(null); setTelegramUrl(''); setDisconnected(false); setError(''); }}>
          {newAccountId && <option value="new">New Telegram account</option>}
          {accounts.map(account => { const identity = account.configuration.telegram as TelegramBotInfo | undefined; return <option key={account.id} value={account.id}>{identity?.botUsername ? `@${identity.botUsername}` : account.name} — {account.status === 'healthy' ? 'Connected' : account.status === 'disabled' ? 'Disconnected' : 'Needs attention'}</option>; })}
        </select></Field>}
        <Button variant="secondary" disabled={!canManage || !agentId || busy || waiting} onClick={() => { setNewAccountId(crypto.randomUUID()); setProvisioning(null); setTelegramUrl(''); setDisconnected(false); setError(''); }}>Add account</Button>
        {newAccountId && <p role="status">New account selected. Click Connect, then use the Telegram account that should own the new bot. Switch accounts in Telegram before pressing Start.</p>}
      </section>
      {agents.error && <p role="alert">Could not load agents.</p>}
      {!agents.loading && !agents.error && !available.length && <p>Create a Telegram agent first. <Link to="/agents" onClick={onClose}>Go to Agents</Link></p>}
      {!connected && <div className="connection-app-fields">
        <h3>Set up your Telegram bot</h3>
        <ol style={{ paddingLeft: '1.5rem', lineHeight: 1.8 }}>
          <li><strong>Open Telegram.</strong> Click Connect below, then press Start in the Telegram chat.</li>
          <li><strong>Create your bot.</strong> Tap the visible Create bot link in the chat and approve the suggested name.</li>
          <li><strong>Confirm your agent.</strong> Return to the manager chat and tap Connect to your agent.</li>
        </ol>
        <p>Your bot name and student link appear here automatically. No tokens to copy.</p>
      </div>}
      {waiting && <div className="catalog-notice" role="status">
        <strong>{provisioning?.status === 'pending' ? 'Next: press Start in Telegram' : provisioning?.status === 'awaiting_bot_creation' ? 'Next: tap Create bot in the Telegram chat' : provisioning?.status === 'awaiting_confirmation' ? 'Next: confirm your agent in Telegram' : 'Finishing your connection...'}</strong>
        <p>Keep this page open. It updates automatically when you finish.</p>
        {trustedTelegramUrl(telegramUrl) && <a className="button button--primary button--md" href={telegramUrl} target="_blank" rel="noopener noreferrer">Open Telegram again</a>}
        <p>If the creation screen does not open, use the latest Telegram mobile or desktop app. After a session expires, click Connect to start again.</p>
      </div>}
      {connected && <><p role="status">Connected</p><TelegramStudentLink bot={bot} /></>}
      {error && <p role="alert" className="catalog-notice catalog-notice--error">{error}</p>}
    </div>
  </Modal>;
}
