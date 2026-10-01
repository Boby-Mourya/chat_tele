import { Button, Card, Field } from '@/components/ui';
import type { SecuritySettings } from './workspaceSettings.api';

export function WorkspaceSessionSettings({ value, disabled, onChange, onSave }: { value: SecuritySettings; disabled: boolean; onChange: (value: SecuritySettings) => void; onSave: () => void }) {
  return <Card className="workspace-panel"><div className="workspace-panel__body">
    <h3>Sessions</h3><p>Workspace access tokens are rejected when they exceed this workspace session age. Existing authentication and logout/session revocation remain in the shared auth pipeline.</p>
    <Field label="Workspace session timeout (minutes)"><input type="number" min={15} max={43200} disabled={disabled} value={value.sessionTimeoutMinutes} onChange={(event) => onChange({ ...value, sessionTimeoutMinutes: Number(event.target.value) })} /></Field>
    <div className="workspace-panel__actions"><Button disabled={disabled} onClick={onSave}>Save session policy</Button></div>
  </div></Card>;
}
