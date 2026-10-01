import { Bot, CheckCircle2, Inbox, MessageSquareText } from 'lucide-react';
import { Link } from 'react-router-dom';
import { formatCompact, relativeTime } from '@/lib/format';
import type { DashboardWidgetRendererProps } from '../dashboard.types';
import { AgentActivityWidget } from './AgentActivityWidget';
import { ChannelHealthWidget } from './ChannelHealthWidget';
import { ConversationSummaryWidget } from './ConversationSummaryWidget';
import { CRMStatusWidget } from './CRMStatusWidget';
import { EducationSummaryWidget } from './EducationSummaryWidget';
import { LeadSummaryWidget } from './LeadSummaryWidget';
import { UsageWidget } from './UsageWidget';
import { TrendRows, WidgetLink, leadStatusRows, widgetTitle } from './widgetHelpers';

export function DashboardWidgetRenderer({ widget, data }: DashboardWidgetRendererProps) {
  const { type, config } = widget;
  const title = widgetTitle(type, config);
  if (data.loading) return <div className="workspace-configured-dashboard__empty" role="status">Loading {title.toLowerCase()}…</div>;
  if (type === 'conversation-summary') return <ConversationSummaryWidget title={title} data={data} />;
  if (type === 'lead-summary') return <LeadSummaryWidget title={title} data={data} />;
  if (type === 'channel-health') return <ChannelHealthWidget title={title} />;
  if (type === 'agent-activity') return <AgentActivityWidget title={title} data={data} />;
  if (type === 'crm-status') return <CRMStatusWidget title={title} />;
  if (type === 'education-summary') return <EducationSummaryWidget title={title} />;
  if (type === 'usage') return <UsageWidget title={title} data={data} />;
  if (type === 'welcome') {
    const message = typeof config.message === 'string' && config.message.trim() ? config.message : 'Use this workspace dashboard to focus on what needs attention.';
    return <div className="workspace-configured-dashboard__content"><h3>{title}</h3><p>{message}</p></div>;
  }
  if (type === 'kpi-cards') return <div className="workspace-configured-dashboard__content"><h3>{title}</h3><div className="workspace-configured-dashboard__stats"><span><Bot /><strong>{data.agents.filter((agent) => agent.status === 'active').length}</strong><small>Active agents</small></span><span><MessageSquareText /><strong>{data.analytics ? formatCompact(data.analytics.conversations) : '—'}</strong><small>7-day conversations</small></span><span><Inbox /><strong>{data.openConversations.length}</strong><small>Open conversations</small></span><span><CheckCircle2 /><strong>{data.leads.length}</strong><small>Leads</small></span></div></div>;
  if (type === 'conversation-chart') return <TrendRows title={title} rows={(data.analytics?.chart ?? []).map((item) => ({ label: item.label, value: item.conversations }))} empty="No conversation trend data yet." />;
  if (type === 'leads-chart') return <TrendRows title={title} rows={leadStatusRows(data.leads)} empty="No lead status data yet." />;
  if (type === 'quick-actions') return <div className="workspace-configured-dashboard__content"><h3>{title}</h3><div className="workspace-configured-dashboard__actions"><Link to="/conversations">Conversations</Link><Link to="/leads">Leads</Link><Link to="/agents">Agents</Link><Link to="/integrations">Integrations</Link></div></div>;
  if (type === 'announcements') {
    const message = typeof config.message === 'string' && config.message.trim() ? config.message : 'No workspace announcement has been configured.';
    return <div className="workspace-configured-dashboard__content"><h3>{title}</h3><p>{message}</p></div>;
  }
  if (type === 'inbox-attention') return <div className="workspace-configured-dashboard__content"><h3>{title}</h3>{data.openConversations.length ? data.openConversations.slice(0, 5).map((item) => <Link className="workspace-configured-dashboard__row" key={item.id} to={`/conversations?selected=${item.id}`}><Inbox /><span><strong>{item.visitorName}</strong><small>{item.preview} · {relativeTime(item.updatedAt)}</small></span></Link>) : <p>You’re all caught up.</p>}</div>;
  return <WidgetLink title={title} description="This published widget is controlled by workspace dashboard configuration." href="/" action="Open workspace" />;
}
