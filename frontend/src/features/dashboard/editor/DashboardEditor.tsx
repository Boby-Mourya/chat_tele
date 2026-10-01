import { useState } from 'react';
import { Button, Card, Field } from '@/components/ui';
import type { DashboardSettings, DashboardWidget } from '@/features/workspace/settings/workspaceSettings.api';
import { LayoutPreview } from './LayoutPreview';
import { WidgetLibrary } from './WidgetLibrary';
import { WidgetSettings } from './WidgetSettings';

export function DashboardEditor({ value, onChange }: { value: DashboardSettings; onChange: (value: DashboardSettings) => void }) {
  const [dragging, setDragging] = useState<string | null>(null);
  const [preview, setPreview] = useState(false);

  function update(next: DashboardSettings) {
    onChange({ ...next, layoutVersion: Math.max(value.layoutVersion + 1, next.layoutVersion) });
  }
  function changeWidget(id: string, next: Partial<DashboardWidget>) {
    update({ ...value, widgets: value.widgets.map((widget) => widget.id === id ? { ...widget, ...next } : widget) });
  }
  function addWidget(type: string) {
    const maxY = value.widgets.reduce((max, widget) => Math.max(max, widget.y + widget.height), 0);
    update({ ...value, widgets: [...value.widgets, { id: crypto.randomUUID(), type, x: 0, y: maxY, width: 4, height: 2, visible: true, audience: [], config: {} }] });
  }
  function moveBefore(targetId: string) {
    if (!dragging || dragging === targetId) return;
    const source = value.widgets.find((widget) => widget.id === dragging);
    if (!source) return;
    const without = value.widgets.filter((widget) => widget.id !== dragging);
    const targetIndex = without.findIndex((widget) => widget.id === targetId);
    without.splice(Math.max(targetIndex, 0), 0, source);
    update({ ...value, widgets: without.map((widget, index) => ({ ...widget, y: index * 2 })) });
  }

  return <Card className="workspace-panel"><div className="workspace-panel__body">
    <div className="page-heading page-heading--split"><div><h3>Dashboard builder</h3><p>Workspace dashboards are saved as configuration and rendered through reusable widgets.</p></div><Button type="button" variant="secondary" onClick={() => setPreview((current) => !current)}>{preview ? 'Hide layout preview' : 'Preview layout'}</Button></div>
    <Field label="Dashboard landing screen"><input value={value.landingScreen} onChange={(event) => update({ ...value, landingScreen: event.target.value })} /></Field>
    <p>Layout version {value.layoutVersion}. Drag widgets to reorder, or use explicit grid coordinates and dimensions.</p>
    <WidgetLibrary onAdd={addWidget} />
    {preview ? <LayoutPreview value={value} /> : null}
    {value.widgets.length === 0 ? <p>No dashboard widgets. Choose a widget above to start the workspace layout.</p> : null}
    {value.widgets.map((widget) => <div key={widget.id} draggable onDragStart={() => setDragging(widget.id)} onDragEnd={() => setDragging(null)} onDragOver={(event) => event.preventDefault()} onDrop={() => moveBefore(widget.id)}>
      <WidgetSettings widget={widget} onChange={(next) => changeWidget(widget.id, next)} onRemove={() => update({ ...value, widgets: value.widgets.filter((item) => item.id !== widget.id) })} />
    </div>)}
  </div></Card>;
}
