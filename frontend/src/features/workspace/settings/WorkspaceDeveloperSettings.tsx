import { Button, Card, Field, Switch } from '@/components/ui';
import { WorkspaceAPIKeysPanel } from '@/components/WorkspaceAPIKeysPanel';
import type { WorkspaceSettings } from '@/lib/workspace-api';
import type { WorkspaceSettingsBundle } from './workspaceSettings.api';

const splitValues = (value: string) => value.split(/[\n,]/).map((item) => item.trim()).filter(Boolean);

export function WorkspaceDeveloperSettings({
  workspace,
  bundle,
  disabled,
  onBundle,
  onSave,
}: {
  workspace: WorkspaceSettings;
  bundle: WorkspaceSettingsBundle;
  disabled: boolean;
  onBundle: (value: WorkspaceSettingsBundle) => void;
  onSave: () => void;
}) {
  const developer = bundle.developer;
  const update = (next: Partial<typeof developer>) => onBundle({ ...bundle, developer: { ...developer, ...next } });
  return <>
    <Card className="workspace-panel"><div className="workspace-panel__body">
      <h3>Developer policy</h3><p>Workspace-level controls for API usage and the existing webhook delivery pipeline.</p>
      <Switch checked={developer.sandboxMode} disabled={disabled} onChange={(sandboxMode) => update({ sandboxMode })} label="Sandbox / test mode" />
      <Switch checked={developer.webhookSigningEnabled} disabled={disabled} onChange={(webhookSigningEnabled) => update({ webhookSigningEnabled })} label="Webhook signing" description="Keep outbound webhook signing enabled for integrations in this workspace." />
      <div className="two-fields"><Field label="API rate limit / minute"><input type="number" min={10} max={100000} disabled={disabled} value={developer.rateLimitPerMinute} onChange={(event) => update({ rateLimitPerMinute: Number(event.target.value) })} /></Field><Field label="Request log retention (days)"><input type="number" min={1} max={365} disabled={disabled} value={developer.requestLogRetentionDays} onChange={(event) => update({ requestLogRetentionDays: Number(event.target.value) })} /></Field></div>
      <Field label="Webhook retry limit"><input type="number" min={0} max={20} disabled={disabled} value={developer.webhookRetryLimit} onChange={(event) => update({ webhookRetryLimit: Number(event.target.value) })} /></Field>
      <Field label="Webhook event subscriptions"><textarea disabled={disabled} value={developer.webhookEvents.join('\n')} placeholder={'conversation.created\nlead.updated'} onChange={(event) => update({ webhookEvents: splitValues(event.target.value) })} /></Field>
      <div className="workspace-panel__actions"><Button disabled={disabled} onClick={onSave}>Save developer policy</Button></div>
    </div></Card>
    <WorkspaceAPIKeysPanel workspace={workspace} />
    <Card className="workspace-panel"><div className="workspace-panel__body"><h3>OAuth applications & webhooks</h3><p>Connection credentials, OAuth applications, webhook endpoints, delivery status, and retries stay in the existing integration pipeline so there is one source of truth.</p><div className="workspace-panel__actions"><a className="button button--secondary button--md" href="/integrations">Open integrations & webhooks</a><a className="button button--secondary button--md" href="/audit">Open request / audit history</a></div></div></Card>
  </>;
}
