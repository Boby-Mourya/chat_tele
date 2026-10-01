import { Button, Card, Field, Switch } from '@/components/ui';
import type { BusinessHours } from './workspaceSettings.api';

const DAYS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'] as const;

export function WorkspaceBusinessHoursSettings({ value, disabled, onChange, onSave }: { value: BusinessHours; disabled: boolean; onChange: (value: BusinessHours) => void; onSave: () => void }) {
  function setDay(day: string, valueText: string) {
    const schedule = { ...value.schedule };
    const ranges = valueText.split(',').map((item) => item.trim()).filter(Boolean);
    if (ranges.length) schedule[day] = ranges;
    else delete schedule[day];
    onChange({ ...value, schedule });
  }

  return <Card className="workspace-panel"><div className="workspace-panel__body">
    <h3>Business hours</h3><p>Workspace operating hours are shared by routing, escalation, and branded widget offline behavior.</p>
    <Switch checked={value.enabled} disabled={disabled} onChange={(enabled) => onChange({ ...value, enabled })} label="Enable workspace business hours" />
    <Field label="Timezone"><input disabled={disabled} value={value.timezone} onChange={(event) => onChange({ ...value, timezone: event.target.value })} /></Field>
    {DAYS.map((day) => <Field key={day} label={day.charAt(0).toUpperCase() + day.slice(1)}><input disabled={disabled || !value.enabled} value={(value.schedule[day] ?? []).join(', ')} placeholder="09:00-17:00" onChange={(event) => setDay(day, event.target.value)} /><small>Use 24-hour ranges; separate multiple ranges with commas.</small></Field>)}
    <div className="workspace-panel__actions"><Button disabled={disabled} onClick={onSave}>Save business hours</Button></div>
  </div></Card>;
}
