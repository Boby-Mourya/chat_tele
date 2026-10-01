import { Button, Field, Switch } from '@/components/ui';
import type { DashboardWidget } from '@/features/workspace/settings/workspaceSettings.api';
import { DASHBOARD_WIDGET_TYPES } from './WidgetLibrary';

export function WidgetSettings({ widget, onChange, onRemove }: { widget: DashboardWidget; onChange: (next: Partial<DashboardWidget>) => void; onRemove: () => void }) {
  return <div className="setup-resource">
    <div className="two-fields"><Field label="Widget type"><select value={widget.type} onChange={(event) => onChange({ type: event.target.value })}>{DASHBOARD_WIDGET_TYPES.map((type) => <option key={type} value={type}>{type.replaceAll('-', ' ')}</option>)}</select></Field><Field label="Audience roles / IDs"><input value={widget.audience.join(', ')} placeholder="Leave empty for everyone" onChange={(event) => onChange({ audience: event.target.value.split(',').map((item) => item.trim()).filter(Boolean) })} /></Field></div>
    <div className="two-fields"><Field label="Grid X"><input type="number" min={0} max={24} value={widget.x} onChange={(event) => onChange({ x: Number(event.target.value) })} /></Field><Field label="Grid Y"><input type="number" min={0} max={1000} value={widget.y} onChange={(event) => onChange({ y: Number(event.target.value) })} /></Field></div>
    <div className="two-fields"><Field label="Width"><input type="number" min={1} max={24} value={widget.width} onChange={(event) => onChange({ width: Number(event.target.value) })} /></Field><Field label="Height"><input type="number" min={1} max={24} value={widget.height} onChange={(event) => onChange({ height: Number(event.target.value) })} /></Field></div>
    <Switch checked={widget.visible} onChange={(visible) => onChange({ visible })} label="Visible" />
    <Field label="Widget config (JSON)"><textarea value={JSON.stringify(widget.config, null, 2)} onChange={(event) => { try { onChange({ config: JSON.parse(event.target.value) as Record<string, unknown> }); } catch { /* keep last valid config while editing */ } }} /></Field>
    <Button type="button" variant="danger" onClick={onRemove}>Remove widget</Button>
  </div>;
}
