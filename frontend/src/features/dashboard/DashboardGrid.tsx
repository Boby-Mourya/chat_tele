import type { DashboardWidget } from '@/features/workspace/settings/workspaceSettings.api';

export function DashboardGrid({ widgets, renderWidget }: { widgets: DashboardWidget[]; renderWidget: (widget: DashboardWidget) => React.ReactNode }) {
  return <div className="workspace-configured-dashboard__grid">
    {widgets.map((widget) => <section
      key={widget.id}
      className="card workspace-configured-dashboard__widget"
      style={{
        gridColumn: `${Math.max(1, widget.x + 1)} / span ${Math.max(1, widget.width)}`,
        gridRow: `${Math.max(1, widget.y + 1)} / span ${Math.max(1, widget.height)}`,
      }}
    >{renderWidget(widget)}</section>)}
  </div>;
}
