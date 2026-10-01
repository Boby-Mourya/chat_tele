import { ChannelBreakdown } from '@/components/channel-breakdown';
import {
  ArrowDownRight,
  ArrowUpRight,
  Bot,
  CheckCircle2,
  Clock3,
  Download,
  GraduationCap,
  HelpCircle,
  MessageSquareText,
  RefreshCw,
  Star,
  Target,
  Users,
  Workflow,
} from 'lucide-react';
import { useState } from 'react';
import { Badge, Button, Card, PageLoader } from '@/components/ui';
import { analyticsApi, type AnalyticsPeriodDays } from '@/lib/analytics-api';
import { formatCompact, formatPercent } from '@/lib/format';
import { useApi } from '@/lib/use-api';
import type { AnalyticsSummary } from '@/types';

const EMPTY_AGENTS = { total: 0, active: 0, support: 0, leadGeneration: 0, education: 0 };
const EMPTY_LEADS = { created: 0, qualified: 0, converted: 0, qualificationRate: 0, conversionRate: 0 };
const EMPTY_CRM = { deliveries: 0, verified: 0, failed: 0, successRate: 0 };
const EMPTY_EDUCATION = { students: 0, activeEnrollments: 0, conversations: 0, activityEvents: 0 };

export function AnalyticsPage() {
  const [days, setDays] = useState<AnalyticsPeriodDays>(30);
  const result = useApi(() => analyticsApi.summary(days), [days]);
  const data = result.data;
  if (result.loading && !data) return <PageLoader />;
  if (!data) return <div className="page analytics-page"><Card><h3>Analytics could not be loaded</h3><p>{result.error ?? 'Try again.'}</p><Button variant="secondary" icon={RefreshCw} onClick={result.reload}>Retry</Button></Card></div>;

  const agents = data.agents ?? EMPTY_AGENTS;
  const leads = data.leads ?? EMPTY_LEADS;
  const crm = data.crm ?? EMPTY_CRM;
  const education = data.education ?? EMPTY_EDUCATION;
  const cards = [
    { label: 'Total conversations', value: formatCompact(data.conversations), delta: data.conversationsDelta, icon: MessageSquareText, color: 'blue' },
    { label: 'AI resolution rate', value: formatPercent(data.resolutionRate), delta: data.resolutionDelta, icon: CheckCircle2, color: 'green' },
    { label: 'Average response', value: `${data.avgResponseSeconds}s`, icon: Clock3, color: 'purple' },
    { label: 'Visitor satisfaction', value: `${data.satisfaction}/5`, icon: Star, color: 'orange' },
  ];
  const outcomeCards = [
    { label: 'Leads created', value: formatCompact(leads.created), note: `${formatPercent(leads.qualificationRate)} qualified`, icon: Target, color: 'blue' },
    { label: 'CRM verified', value: formatCompact(crm.verified), note: `${formatPercent(crm.successRate)} delivery success`, icon: Workflow, color: 'green' },
    { label: 'Active students', value: formatCompact(education.students), note: `${formatCompact(education.activeEnrollments)} active enrollments`, icon: GraduationCap, color: 'purple' },
    { label: 'Active agents', value: formatCompact(agents.active), note: `${formatCompact(agents.total)} total agents`, icon: Users, color: 'orange' },
  ];

  return <div className="page analytics-page">
    <div className="page-heading page-heading--split">
      <div><h2>Analytics</h2><p>Understand performance, lead outcomes, CRM delivery, and education activity in the active workspace.</p></div>
      <div className="heading-actions">
        <select value={String(days)} aria-label="Analytics period" onChange={(event) => setDays(Number(event.target.value) as AnalyticsPeriodDays)}>
          <option value="7">Last 7 days</option><option value="30">Last 30 days</option><option value="90">Last 90 days</option>
        </select>
        <Button variant="secondary" icon={Download} onClick={() => exportAnalytics(data)}>Export</Button>
      </div>
    </div>

    <div className="stat-grid">{cards.map(({ label, value, delta, icon: Icon, color }) => <Card className="stat-card analytics-stat" key={label}>
      <div className={`stat-card__icon stat-card__icon--${color}`}><Icon /></div><span>{label}<HelpCircle /></span><strong>{value}</strong>
      {delta == null ? <small><em>{data.period}</em></small> : <small className={delta >= 0 ? 'positive' : 'negative'}>{delta >= 0 ? <ArrowUpRight /> : <ArrowDownRight />}{Math.abs(delta)}% <em>vs previous period</em></small>}
    </Card>)}</div>

    <Card className="analytics-chart-card"><div className="card-heading"><div><h3>Conversations & resolutions</h3><p>{data.period} · all accessible agents in this workspace</p></div><div className="chart-legend"><span><i className="legend-dot legend-dot--blue"/> Conversations</span><span><i className="legend-dot legend-dot--mint"/> Resolved by AI</span></div></div><AnalyticsChart data={data.chart} /></Card>

    <div className="stat-grid">{outcomeCards.map(({ label, value, note, icon: Icon, color }) => <Card className="stat-card analytics-stat" key={label}><div className={`stat-card__icon stat-card__icon--${color}`}><Icon /></div><span>{label}</span><strong>{value}</strong><small><em>{note}</em></small></Card>)}</div>

    <div className="analytics-lower-grid">
      <Card className="top-questions"><div className="card-heading"><div><h3>Lead & CRM outcomes</h3><p>Workspace-scoped funnel and delivery health</p></div><Badge tone="brand">Business</Badge></div><MetricRows rows={[
        ['Qualified leads', leads.qualified, `${formatPercent(leads.qualificationRate)} of new leads`],
        ['Converted leads', leads.converted, `${formatPercent(leads.conversionRate)} of new leads`],
        ['CRM deliveries', crm.deliveries, `${crm.verified} verified`],
        ['CRM failures', crm.failed, `${formatPercent(crm.successRate)} verified success rate`],
      ]} /></Card>
      <Card className="top-questions"><div className="card-heading"><div><h3>Education & agent mix</h3><p>Student access and agent-purpose activity</p></div><Badge tone="brand">Education</Badge></div><MetricRows rows={[
        ['Education conversations', education.conversations, `${education.activityEvents} activity events`],
        ['Active enrollments', education.activeEnrollments, `${education.students} active students`],
        ['Lead-generation agents', agents.leadGeneration, `${agents.active} agents active`],
        ['Education agents', agents.education, `${agents.support} support agents`],
      ]} /></Card>
    </div>

    <div className="analytics-lower-grid"><Card className="top-questions"><div className="card-heading"><div><h3>Top questions</h3><p>What visitors ask most often</p></div><Badge tone="brand">Knowledge insights</Badge></div><div className="question-list">{data.topQuestions.map((item, index) => <div key={item.question}><span className="question-rank">{index + 1}</span><span><strong>{item.question}</strong><small>{item.count} conversations</small></span><div className="resolution-bar"><span><i style={{ width: `${item.resolutionRate}%` }} /></span><small>{item.resolutionRate}% resolved</small></div></div>)}</div></Card>
      <Card className="channel-card"><div className="card-heading"><div><h3>Channels</h3><p>Where conversations begin</p></div></div><ChannelBreakdown channels={data.channels} total={data.conversations} /></Card>
    </div>

    <Card className="health-insight"><span><Bot /></span><div><h3>Cross-domain analytics are live</h3><p>{leads.created} leads, {crm.verified} verified CRM deliveries, and {education.conversations} education conversations are included for {data.period.toLowerCase()}.</p></div><Button variant="secondary" icon={RefreshCw} onClick={result.reload}>Refresh</Button></Card>
  </div>;
}

function MetricRows({ rows }: { rows: Array<[string, number, string]> }) {
  return <div className="question-list">{rows.map(([label, value, detail], index) => <div key={label}><span className="question-rank">{index + 1}</span><span><strong>{label}</strong><small>{detail}</small></span><strong>{formatCompact(value)}</strong></div>)}</div>;
}

function AnalyticsChart({ data }: { data: Array<{ label: string; conversations: number; resolved: number }> }) {
  const max = Math.max(...data.flatMap((item) => [item.conversations, item.resolved]), 1);
  return <div className="bar-chart"><div className="bar-y-labels"><span>{max}</span><span>{Math.round(max * .66)}</span><span>{Math.round(max * .33)}</span><span>0</span></div><div className="bar-plot"><div className="bar-grid"><i/><i/><i/><i/></div>{data.map((item) => <div className="bar-group" key={item.label}><div className="bar-pair"><i style={{ height: `${item.conversations / max * 100}%` }} title={`${item.conversations} conversations`} /><i style={{ height: `${item.resolved / max * 100}%` }} title={`${item.resolved} resolved`} /></div><span>{item.label}</span></div>)}</div></div>;
}

function exportAnalytics(data: AnalyticsSummary): void {
  const agents = data.agents ?? EMPTY_AGENTS;
  const leads = data.leads ?? EMPTY_LEADS;
  const crm = data.crm ?? EMPTY_CRM;
  const education = data.education ?? EMPTY_EDUCATION;
  const rows = [
    ['Metric', 'Value'], ['Period', data.period], ['Conversations', data.conversations], ['Resolution rate', data.resolutionRate], ['Average response seconds', data.avgResponseSeconds], ['Satisfaction', data.satisfaction],
    ['Active agents', agents.active], ['Total agents', agents.total], ['Leads created', leads.created], ['Qualified leads', leads.qualified], ['Converted leads', leads.converted],
    ['CRM deliveries', crm.deliveries], ['CRM verified', crm.verified], ['CRM failed', crm.failed], ['Active students', education.students], ['Active enrollments', education.activeEnrollments], ['Education conversations', education.conversations], ['Education activity events', education.activityEvents],
  ];
  const csv = rows.map((row) => row.map((value) => `"${String(value).replaceAll('"', '""')}"`).join(',')).join('\n');
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
  const anchor = document.createElement('a');
  anchor.href = url; anchor.download = `northstar-analytics-${data.period.toLowerCase().replaceAll(' ', '-')}.csv`; anchor.click();
  URL.revokeObjectURL(url);
}
