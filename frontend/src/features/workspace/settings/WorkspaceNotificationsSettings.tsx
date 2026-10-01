import { Button, Card, Field, Switch } from '@/components/ui';
import type { WorkspaceSettingsBundle } from './workspaceSettings.api';

export function WorkspaceNotificationsSettings({
  bundle,
  disabled,
  onBundle,
  onSave,
}: {
  bundle: WorkspaceSettingsBundle;
  disabled: boolean;
  onBundle: (value: WorkspaceSettingsBundle) => void;
  onSave: () => void;
}) {
  const value = bundle.notifications;
  const toggle = (key: keyof typeof value, checked: boolean) => onBundle({ ...bundle, notifications: { ...value, [key]: checked } });
  return <Card className="workspace-panel"><div className="workspace-panel__body">
    <h3>Workspace notifications</h3><p>Choose which workspace administration and operational events should notify configured recipients.</p>
    {(['memberChanges', 'securityAlerts', 'billingAlerts', 'channelFailures', 'integrationFailures', 'weeklyDigest'] as const).map((key) => <Switch key={key} disabled={disabled} checked={value[key] as boolean} onChange={(checked) => toggle(key, checked)} label={key.replace(/([A-Z])/g, ' $1')} />)}
    <Field label="Recipients"><textarea disabled={disabled} value={value.recipients.join('\n')} placeholder={'ops@example.com\nsecurity@example.com'} onChange={(event) => onBundle({ ...bundle, notifications: { ...value, recipients: event.target.value.split(/[\n,]/).map((item) => item.trim()).filter(Boolean) } })} /></Field>
    <div className="workspace-panel__actions"><Button disabled={disabled} onClick={onSave}>Save notifications</Button></div>
  </div></Card>;
}
