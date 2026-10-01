import { CheckCircle2, Clock3 } from 'lucide-react';
import { Link } from 'react-router-dom';
import type { DashboardData } from '../dashboard.types';

export function LeadSummaryWidget({ title, data }: { title: string; data: DashboardData }) {
  const qualified = data.leads.filter((lead) => lead.status.toLowerCase().includes('qualified')).length;
  return <div className="workspace-configured-dashboard__content"><h3>{title}</h3><div className="workspace-configured-dashboard__stats"><span><CheckCircle2 /><strong>{data.leads.length}</strong><small>Total leads</small></span><span><Clock3 /><strong>{qualified}</strong><small>Qualified</small></span></div><Link to="/leads">Open leads</Link></div>;
}
