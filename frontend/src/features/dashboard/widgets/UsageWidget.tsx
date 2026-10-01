import { Bot, MessageSquareText } from 'lucide-react';
import { formatCompact } from '@/lib/format';
import type { DashboardData } from '../dashboard.types';

export function UsageWidget({ title, data }: { title: string; data: DashboardData }) {
  return <div className="workspace-configured-dashboard__content"><h3>{title}</h3><div className="workspace-configured-dashboard__stats"><span><Bot /><strong>{data.agents.filter((agent) => agent.status === 'active').length}</strong><small>Active agents</small></span><span><MessageSquareText /><strong>{data.analytics ? formatCompact(data.analytics.conversations) : '—'}</strong><small>7-day conversations</small></span></div></div>;
}
