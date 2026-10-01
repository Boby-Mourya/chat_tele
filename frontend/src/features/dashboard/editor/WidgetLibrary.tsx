import { Button } from '@/components/ui';

export const DASHBOARD_WIDGET_TYPES = [
  'welcome', 'kpi-cards', 'conversation-summary', 'conversation-chart', 'lead-summary', 'leads-chart',
  'channel-health', 'agent-activity', 'crm-status', 'education-summary', 'quick-actions', 'announcements', 'usage',
] as const;

export function WidgetLibrary({ onAdd }: { onAdd: (type: string) => void }) {
  return <div className="workspace-branding-tabs" aria-label="Dashboard widget library">{DASHBOARD_WIDGET_TYPES.map((type) => <Button key={type} type="button" variant="secondary" onClick={() => onAdd(type)}>{type.replaceAll('-', ' ')}</Button>)}</div>;
}
