import { CheckCircle2, Clock3, MessageSquareText } from 'lucide-react';
import { Link } from 'react-router-dom';
import { formatCompact, formatPercent } from '@/lib/format';
import type { DashboardData } from '../dashboard.types';

export function ConversationSummaryWidget({ title, data }: { title: string; data: DashboardData }) {
  return <div className="workspace-configured-dashboard__content"><h3>{title}</h3><div className="workspace-configured-dashboard__stats"><span><MessageSquareText /><strong>{data.analytics ? formatCompact(data.analytics.conversations) : '—'}</strong><small>Conversations</small></span><span><CheckCircle2 /><strong>{data.analytics ? formatPercent(data.analytics.resolutionRate) : '—'}</strong><small>Resolved by AI</small></span><span><Clock3 /><strong>{data.analytics ? `${data.analytics.avgResponseSeconds}s` : '—'}</strong><small>Avg. response</small></span></div><Link to="/conversations">Open conversations</Link></div>;
}
