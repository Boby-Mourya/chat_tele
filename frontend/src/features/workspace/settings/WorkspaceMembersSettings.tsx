import { useCallback, useEffect, useState } from 'react';
import { Badge, Button, Card } from '@/components/ui';
import { useToast } from '@/components/providers';
import { WorkspaceTeamPanel } from '@/components/WorkspaceTeamPanel';
import {
  workspaceTeamApi,
  type WorkspaceMember,
  type WorkspaceMemberLifecycle,
} from '@/lib/workspace-team-api';
import type { WorkspaceSettings } from '@/lib/workspace-api';

export function WorkspaceMembersSettings({ workspace }: { workspace: WorkspaceSettings }) {
  const { pushToast } = useToast();
  const [members, setMembers] = useState<WorkspaceMember[]>([]);
  const [lifecycle, setLifecycle] = useState<Record<string, WorkspaceMemberLifecycle>>({});
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState('');
  const [error, setError] = useState('');
  const canManage = workspace.permissions?.includes('members.manage') ?? false;

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [memberValues, lifecycleValues] = await Promise.all([
        workspaceTeamApi.listMembers(),
        workspaceTeamApi.listMemberLifecycle(),
      ]);
      setMembers(memberValues);
      setLifecycle(Object.fromEntries(lifecycleValues.map((value) => [value.userId, value])));
      setError('');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Member lifecycle could not be loaded');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => { void load(); }, 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  async function mutate(userId: string, work: () => Promise<WorkspaceMemberLifecycle>, success: string) {
    setBusyId(userId);
    try {
      const value = await work();
      setLifecycle((current) => ({ ...current, [value.userId]: value }));
      if (success === 'Ownership transferred') {
        setMembers((current) => current.map((member) => member.userId === userId ? { ...member, role: 'workspace_admin' } : member));
      }
      pushToast(success);
    } catch (reason) {
      pushToast(reason instanceof Error ? reason.message : 'Member change failed', 'error');
    } finally {
      setBusyId('');
    }
  }

  return <>
    <WorkspaceTeamPanel workspace={workspace} />
    <Card className="workspace-panel">
      <div className="workspace-panel__body">
        <div className="page-heading page-heading--split"><div><h3>Member lifecycle</h3><p>Workspace-only suspension, MFA state, last activity, team membership, and ownership transfer.</p></div><Button variant="secondary" disabled={loading || !!busyId} onClick={() => void load()}>Refresh</Button></div>
        {error ? <p role="alert">{error}</p> : null}
        {loading ? <p role="status">Loading member lifecycle…</p> : null}
        {!loading && members.length === 0 ? <p>No workspace members.</p> : null}
        {!loading ? <div className="workspace-member-list">{members.map((member) => {
          const state = lifecycle[member.userId];
          const suspended = state?.status === 'suspended';
          return <div key={member.userId}>
            <span className="mini-avatar">{member.name.charAt(0).toUpperCase()}</span>
            <span><strong>{member.name}{member.isSelf ? ' (you)' : ''}</strong><small>{member.email} · MFA {state?.mfaEnabled ? 'enabled' : 'not enabled'} · Last active {state?.lastActive ? new Date(state.lastActive).toLocaleString() : 'not recorded'} · {state?.teamIds.length ?? 0} teams</small></span>
            <Badge tone={suspended ? 'danger' : 'success'}>{state?.status ?? 'active'}</Badge>
            {canManage && !member.isSelf ? <span className="workspace-member-list__actions">
              {suspended ? <Button size="sm" variant="secondary" disabled={busyId === member.userId} onClick={() => void mutate(member.userId, () => workspaceTeamApi.reactivateMember(member.userId), 'Member reactivated')}>Reactivate</Button> : <Button size="sm" variant="secondary" disabled={busyId === member.userId} onClick={() => { if (window.confirm(`Suspend ${member.name} from ${workspace.name}?`)) void mutate(member.userId, () => workspaceTeamApi.suspendMember(member.userId), 'Member suspended'); }}>Suspend</Button>}
              {!suspended && workspace.role === 'workspace_admin' ? <Button size="sm" variant="ghost" disabled={busyId === member.userId} onClick={() => { if (window.confirm(`Transfer workspace ownership to ${member.name}? This promotes them to workspace administrator.`)) void mutate(member.userId, () => workspaceTeamApi.transferOwnership(member.userId), 'Ownership transferred'); }}>Transfer ownership</Button> : null}
            </span> : null}
          </div>;
        })}</div> : null}
      </div>
    </Card>
  </>;
}
