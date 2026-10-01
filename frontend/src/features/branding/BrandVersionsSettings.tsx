import { Button, Card } from '@/components/ui';
import type { BrandVersion } from '@/features/workspace/settings/workspaceSettings.api';

export function BrandVersionsSettings({ versions, busy, canRollback, onRollback }: { versions: BrandVersion[]; busy: boolean; canRollback: boolean; onRollback: (version: number) => void }) {
  return <Card className="workspace-panel"><div className="workspace-panel__body">
    <h3>Brand publication history</h3><p>Every publish and rollback creates a new immutable version entry; rollback never edits an old version in place.</p>
    {versions.length === 0 ? <p>No published brand versions yet.</p> : [...versions].reverse().map((version) => <div className="setup-resource" key={version.version}>
      <strong>Version {version.version}</strong><p>{new Date(version.publishedAt).toLocaleString()} · {version.changeNote || 'No change note'} · actor {version.createdBy}</p>
      {canRollback ? <Button type="button" variant="secondary" disabled={busy} onClick={() => { if (window.confirm(`Publish a new version using version ${version.version} as the source?`)) onRollback(version.version); }}>Rollback to this version</Button> : null}
    </div>)}
  </div></Card>;
}
