import { Bot } from 'lucide-react';
import { Link } from 'react-router-dom';
import { formatCompact } from '@/lib/format';
import type { DashboardData } from '../dashboard.types';

export function AgentActivityWidget({ title, data }: { title: string; data: DashboardData }) {
  return <div className="workspace-configured-dashboard__content"><h3>{title}</h3>{data.agents.length ? data.agents.slice(0, 5).map((agent) => <Link className="workspace-configured-dashboard__row" key={agent.id} to={`/agents/${agent.id}/instructions`}><Bot /><span><strong>{agent.name}</strong><small>{agent.status} · {formatCompact(agent.conversations)} conversations</small></span></Link>) : <p>No agents yet.</p>}</div>;
}
