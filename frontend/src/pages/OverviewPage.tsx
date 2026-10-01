import { ArrowLeft, ArrowRight, Bot, CheckCircle2, Clock3, Inbox, MessageSquareText, Plus } from 'lucide-react';
import { Link } from 'react-router-dom';
import { useState } from 'react';
import { useAuth } from '@/components/providers';
import { Badge, Button, EmptyState } from '@/components/ui';
import { DashboardTrend, DashboardWelcome, LearningTip } from '@/components/academy-dashboard';
import { WorkspaceConfiguredDashboard } from '@/features/dashboard/WorkspaceConfiguredDashboard';
import { useWorkspaceBrandRuntime } from '@/features/branding/WorkspaceBrandRuntime';
import { api } from '@/lib/api';
import { formatCompact, formatPercent, relativeTime } from '@/lib/format';
import { useApi } from '@/lib/use-api';

export function OverviewPage() {
  const brand = useWorkspaceBrandRuntime();
  if (brand?.identity.brandedDashboard && brand.dashboard.widgets.length > 0) {
    return <WorkspaceConfiguredDashboard brand={brand} />;
  }
  return <LegacyOverviewPage />;
}

function LegacyOverviewPage() {
  const { session } = useAuth();
  const agents = useApi(() => api.agents.list());
  const conversations = useApi(() => api.conversations.list());
  const [period, setPeriod] = useState<7 | 30>(7);
  const analytics = useApi(() => api.analytics.summary(period), [period]);
  const [filter, setFilter] = useState('all');
  const [metric, setMetric] = useState<'conversations' | 'resolved'>('conversations');
  const [selected, setSelected] = useState(0);
  const records = agents.data ?? [];
  const featured = records[selected % Math.max(records.length, 1)];
  const shown = records.filter((agent) => filter === 'all' || (filter === 'education' ? agent.purpose === 'education' : agent.status === filter));
  const open = conversations.data?.items.filter((item) => item.state !== 'resolved') ?? [];
  return <div className="page academy-dashboard">
    <div className="academy-dashboard__primary">
      <DashboardWelcome name={session?.user.name?.split(/\s+/)[0] || 'there'}>It’s good to see you again.</DashboardWelcome>
      {featured ? <div className="academy-continue">
        <Link className="academy-continue__record" aria-label={`Continue with ${featured.name}`} to={`/agents/${featured.id}/instructions`}>
          <span className="academy-record-icon"><Bot /></span><span><strong>{featured.name}</strong><small>{featured.appearance.deploymentChannel === 'whatsapp' ? featured.whatsappNumber || 'WhatsApp · number needed' : 'Your AI agent'}</small></span>
          <Badge tone={featured.status === 'active' ? 'success' : 'neutral'}>{featured.status}</Badge><span className="button button--primary">Continue</span>
        </Link>
        <div className="academy-carousel-actions"><button disabled={records.length < 2} aria-label="Previous agent" onClick={() => setSelected((value) => (value + records.length - 1) % records.length)}><ArrowLeft /></button><button disabled={records.length < 2} aria-label="Next agent" onClick={() => setSelected((value) => (value + 1) % records.length)}><ArrowRight /></button></div>
      </div> : null}
      <section className="academy-records">
        <div className="academy-section-heading"><h3>Your agents</h3><Link className="button button--secondary button--sm" to="/agents"><Plus /> Create agent</Link></div>
        <div className="academy-tabs" role="group" aria-label="Filter agents">{[['all', 'All agents'], ['active', 'Active'], ['draft', 'Draft'], ['education', 'Education']].map(([id, label]) => <button key={id} aria-pressed={filter === id} className={filter === id ? 'is-active' : ''} onClick={() => setFilter(id!)}>{label}</button>)}</div>
        {agents.error ? <EmptyState icon={Bot} title="Agents are unavailable" description={agents.error} action={<Button onClick={agents.reload}>Try again</Button>} /> : agents.loading ? <p role="status" className="academy-empty">Loading your agents…</p> : shown.length ? <div className="academy-record-list">{shown.map((agent) => <article className="academy-record" key={agent.id}>
          <span className="academy-record-icon"><Bot /></span><div className="academy-record__name"><h4>{agent.name}</h4><p>{agent.description || `${agent.purpose === 'education' ? 'Education' : 'AI'} assistant`}</p></div>
          <span className="academy-record__metric" title="Conversations"><MessageSquareText />{formatCompact(agent.conversations)}</span><span className="academy-record__metric" title="Resolved by AI"><CheckCircle2 />{formatPercent(agent.resolutionRate)}</span>
          <Link className="button button--secondary" to={`/agents/${agent.id}/instructions`} aria-label={`Open ${agent.name}`}>Open agent</Link>
        </article>)}</div> : <EmptyState icon={Bot} title={records.length ? 'No matching agents' : 'Create your first agent'} description="Build an assistant for your customers or students." action={<Link className="button button--primary" to="/agents">Manage agents</Link>} />}
      </section>
      <section className="academy-attention"><div className="academy-section-heading"><h3>Needs attention</h3><Link to="/conversations">View inbox <ArrowRight /></Link></div>
        {conversations.error ? <p role="alert">{conversations.error} <button className="text-button" onClick={conversations.reload}>Try again</button></p> : conversations.loading ? <p role="status">Loading conversations…</p> : open.length ? open.slice(0, 3).map((item) => <Link className="academy-inbox-row" key={item.id} to={`/conversations?selected=${item.id}`}><span className="mini-avatar">{item.visitorName.charAt(0)}</span><span><strong>{item.visitorName}</strong><small>{item.preview}</small></span><small>{relativeTime(item.updatedAt)}</small></Link>) : <div className="academy-empty"><Inbox /><p>You’re all caught up.</p></div>}
      </section>
    </div>
    <aside className="academy-dashboard__secondary">
      <div className="academy-big-stats"><div><strong>{agents.data ? records.filter((agent) => agent.status === 'active').length : '—'}</strong><span>Agents<br />active</span></div><div><strong>{analytics.data ? formatCompact(analytics.data.conversations) : '—'}</strong><span>Conversations<br />this period</span></div></div>
      <section className="academy-statistics"><h3>Your statistics</h3><div className="academy-statistics__controls"><div className="academy-tabs" role="group" aria-label="Chart metric"><button aria-pressed={metric === 'conversations'} className={metric === 'conversations' ? 'is-active' : ''} onClick={() => setMetric('conversations')}>Conversations</button><button aria-pressed={metric === 'resolved'} className={metric === 'resolved' ? 'is-active' : ''} onClick={() => setMetric('resolved')}>Resolved</button></div><select aria-label="Chart period" value={period} onChange={(event) => setPeriod(Number(event.target.value) as 7 | 30)}><option value="7">Weekly</option><option value="30">Monthly</option></select></div>
        {analytics.error ? <EmptyState icon={MessageSquareText} title="Statistics are unavailable" description={analytics.error} action={<Button onClick={analytics.reload}>Try again</Button>} /> : analytics.loading ? <p className="academy-empty" role="status">Loading statistics…</p> : <DashboardTrend label={metric === 'conversations' ? 'Conversation volume trend' : 'Resolved conversations trend'} data={(analytics.data?.chart ?? []).map((item) => ({ label: item.label, value: item[metric] }))} />}
        <div className="academy-mini-stats"><span><CheckCircle2 /><strong>{analytics.data ? formatPercent(analytics.data.resolutionRate) : '—'}</strong> Resolved by AI</span><span><Clock3 /><strong>{analytics.data ? `${analytics.data.avgResponseSeconds}s` : '—'}</strong> Avg. response</span></div>
      </section>
      <LearningTip description="Give your agents more knowledge. Make every answer more useful." to="/agents" action="Improve your agents" />
    </aside>
  </div>;
}
