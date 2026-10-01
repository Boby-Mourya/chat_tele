import { WidgetLink } from './widgetHelpers';

export function CRMStatusWidget({ title }: { title: string }) {
  return <WidgetLink title={title} description="Review CRM connections and synchronization status." href="/integrations" action="Open CRM integrations" />;
}
