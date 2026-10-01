import { WidgetLink } from './widgetHelpers';

export function EducationSummaryWidget({ title }: { title: string }) {
  return <WidgetLink title={title} description="Open education courses, batches, students, and learning workflows." href="/education" action="Open education" />;
}
