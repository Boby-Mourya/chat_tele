import { WidgetLink } from './widgetHelpers';

export function ChannelHealthWidget({ title }: { title: string }) {
  return <WidgetLink title={title} description="Review channel connections, delivery health, and connection status." href="/integrations" action="Open channels" />;
}
