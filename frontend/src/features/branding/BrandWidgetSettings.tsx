import { Card, Field, Switch } from '@/components/ui';
import type { ExtendedBranding } from '@/features/workspace/settings/workspaceSettings.api';

const DAYS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'] as const;

export function BrandWidgetSettings({ value, onChange }: { value: ExtendedBranding; onChange: (value: ExtendedBranding) => void }) {
  const widget = value.widget;
  const update = (next: Partial<typeof widget>) => onChange({ ...value, widget: { ...widget, ...next } });
  function schedule(day: string, range: string) {
    const next = { ...widget.businessHours.schedule };
    if (range.trim()) next[day] = [range.trim()]; else delete next[day];
    update({ businessHours: { ...widget.businessHours, schedule: next } });
  }
  return <Card className="workspace-panel"><div className="workspace-panel__body">
    <h3>Website chat widget</h3><p>Published widget branding cascades after platform defaults and before channel-specific overrides.</p>
    <div className="two-fields"><Field label="Launcher icon"><input value={widget.launcherIcon} onChange={(event) => update({ launcherIcon: event.target.value })} /></Field><Field label="Widget logo"><input value={widget.widgetLogo} onChange={(event) => update({ widgetLogo: event.target.value })} /></Field></div>
    <div className="two-fields"><Field label="Greeting"><input value={widget.greeting} onChange={(event) => update({ greeting: event.target.value })} /></Field><Field label="Header"><input value={widget.header} onChange={(event) => update({ header: event.target.value })} /></Field></div>
    <div className="two-fields"><Field label="Position"><select value={widget.position} onChange={(event) => update({ position: event.target.value as typeof widget.position })}><option value="bottom-right">Bottom right</option><option value="bottom-left">Bottom left</option></select></Field><Field label="Font"><select value={widget.font} onChange={(event) => update({ font: event.target.value as typeof widget.font })}><option>Inter</option><option>DM Sans</option><option>Manrope</option><option>System UI</option></select></Field></div>
    <div className="two-fields"><Field label="Launcher color"><input type="color" value={widget.launcherColor} onChange={(event) => update({ launcherColor: event.target.value })} /></Field><Field label="Background"><input type="color" value={widget.background} onChange={(event) => update({ background: event.target.value })} /></Field></div>
    <div className="two-fields"><Field label="User message color"><input type="color" value={widget.userMessageColor} onChange={(event) => update({ userMessageColor: event.target.value })} /></Field><Field label="Agent message color"><input type="color" value={widget.agentMessageColor} onChange={(event) => update({ agentMessageColor: event.target.value })} /></Field></div>
    <div className="two-fields"><Field label="Agent avatar"><input value={widget.agentAvatar} onChange={(event) => update({ agentAvatar: event.target.value })} /></Field><Field label="Bot avatar"><input value={widget.botAvatar} onChange={(event) => update({ botAvatar: event.target.value })} /></Field></div>
    <Field label="Privacy link"><input value={widget.privacyUrl} onChange={(event) => update({ privacyUrl: event.target.value })} /></Field>
    <Field label="Powered-by label"><input value={widget.poweredByLabel} onChange={(event) => update({ poweredByLabel: event.target.value })} /></Field>
    <Field label="Offline message"><textarea value={widget.offlineMessage} onChange={(event) => update({ offlineMessage: event.target.value })} /></Field>
    <Switch checked={widget.businessHours.enabled} onChange={(enabled) => update({ businessHours: { ...widget.businessHours, enabled } })} label="Widget business hours" />
    {widget.businessHours.enabled ? <div className="setup-resource"><Field label="Timezone"><input value={widget.businessHours.timezone} onChange={(event) => update({ businessHours: { ...widget.businessHours, timezone: event.target.value } })} /></Field>{DAYS.map((day) => <Field key={day} label={day.charAt(0).toUpperCase() + day.slice(1)}><input value={widget.businessHours.schedule[day]?.[0] ?? ''} placeholder="09:00-17:00" onChange={(event) => schedule(day, event.target.value)} /></Field>)}</div> : null}
  </div></Card>;
}
