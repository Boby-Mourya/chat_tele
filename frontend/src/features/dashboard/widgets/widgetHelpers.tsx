import { Link } from 'react-router-dom';
import type { Lead } from '@/types';

export function WidgetLink({ title, description, href, action }: { title: string; description: string; href: string; action: string }) {
  return <div className="workspace-configured-dashboard__content"><h3>{title}</h3><p>{description}</p><Link to={href}>{action}</Link></div>;
}

export function TrendRows({ title, rows, empty }: { title: string; rows: Array<{ label: string; value: number }>; empty: string }) {
  const maximum = Math.max(1, ...rows.map((row) => row.value));
  return <div className="workspace-configured-dashboard__content"><h3>{title}</h3>{rows.length ? <div className="workspace-configured-dashboard__trend">{rows.map((row) => <div key={row.label}><span>{row.label}</span><div><i style={{ width: `${Math.max(2, Math.round((row.value / maximum) * 100))}%` }} /></div><strong>{row.value}</strong></div>)}</div> : <p>{empty}</p>}</div>;
}

export function leadStatusRows(leads: Lead[]): Array<{ label: string; value: number }> {
  const counts = new Map<string, number>();
  for (const lead of leads) counts.set(lead.status || 'unknown', (counts.get(lead.status || 'unknown') ?? 0) + 1);
  return [...counts.entries()].sort((left, right) => right[1] - left[1]).map(([label, value]) => ({ label, value }));
}

export function widgetTitle(type: string, config: Record<string, unknown>): string {
  return typeof config.title === 'string' && config.title.trim()
    ? config.title
    : type.split('-').map((part) => part.charAt(0).toUpperCase() + part.slice(1)).join(' ');
}
