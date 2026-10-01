import type { DashboardSettings } from '@/features/workspace/settings/workspaceSettings.api';

export function LayoutPreview({ value }: { value: DashboardSettings }) {
  return <div className="workspace-configured-dashboard__grid" aria-label="Dashboard layout preview">
    {value.widgets.filter((widget) => widget.visible).map((widget) => <div key={widget.id} className="card workspace-configured-dashboard__widget" style={{ gridColumn: `${Math.max(1, widget.x + 1)} / span ${Math.max(1, widget.width)}`, gridRow: `${Math.max(1, widget.y + 1)} / span ${Math.max(1, widget.height)}` }}><strong>{widget.type.replaceAll('-', ' ')}</strong><small>{widget.width}×{widget.height} · x{widget.x} y{widget.y}</small></div>)}
  </div>;
}
