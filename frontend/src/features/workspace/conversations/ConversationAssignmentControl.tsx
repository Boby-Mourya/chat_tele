import { useEffect, useState } from 'react';
import { useToast, useWorkspace } from '@/components/providers';
import { Button } from '@/components/ui';
import {
  workspaceSettingsApi,
  type ConversationAssignment,
  type ConversationAssignmentOptions,
} from '@/features/workspace/settings/workspaceSettings.api';
import './ConversationAssignmentControl.css';

export function ConversationAssignmentControl({ conversationId }: { conversationId: string }) {
  const { activeWorkspace } = useWorkspace();
  const { pushToast } = useToast();
  const canAssign = activeWorkspace?.permissions?.includes('conversations.assign') ?? false;
  const [options, setOptions] = useState<ConversationAssignmentOptions | null>(null);
  const [assignment, setAssignment] = useState<ConversationAssignment | null>(null);
  const [userId, setUserId] = useState('');
  const [teamId, setTeamId] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!canAssign) return;
    let current = true;
    setError('');
    Promise.all([
      workspaceSettingsApi.assignmentOptions(),
      workspaceSettingsApi.getConversationAssignment(conversationId),
    ]).then(([nextOptions, nextAssignment]) => {
      if (!current) return;
      setOptions(nextOptions);
      setAssignment(nextAssignment);
      setUserId(nextAssignment.userId ?? '');
      setTeamId(nextAssignment.teamId ?? '');
    }).catch((reason: unknown) => {
      if (current) setError(reason instanceof Error ? reason.message : 'Assignment could not be loaded');
    });
    return () => { current = false; };
  }, [canAssign, conversationId, activeWorkspace?.id]);

  if (!canAssign) return null;

  async function save() {
    setBusy(true);
    setError('');
    try {
      const saved = userId || teamId
        ? await workspaceSettingsApi.saveConversationAssignment(conversationId, userId || null, teamId || null)
        : await workspaceSettingsApi.clearConversationAssignment(conversationId);
      setAssignment(saved);
      setUserId(saved.userId ?? '');
      setTeamId(saved.teamId ?? '');
      pushToast(saved.userId || saved.teamId ? 'Conversation assignment saved' : 'Conversation assignment cleared');
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : 'Conversation assignment could not be saved';
      setError(message);
      pushToast(message, 'error');
    } finally {
      setBusy(false);
    }
  }

  return <section className="conversation-assignment-control">
    <strong>Conversation assignment</strong>
    <p>Assigned/team conversation scopes use this workspace assignment.</p>
    {!options && !error ? <small>Loading assignment options…</small> : null}
    {options ? <>
      <label>Assigned member<select value={userId} disabled={busy} onChange={(event) => setUserId(event.target.value)}><option value="">Unassigned</option>{options.members.map((member) => <option key={member.id} value={member.id}>{member.name} · {member.role}</option>)}</select></label>
      <label>Assigned team<select value={teamId} disabled={busy} onChange={(event) => setTeamId(event.target.value)}><option value="">No team</option>{options.teams.map((team) => <option key={team.id} value={team.id}>{team.name}</option>)}</select></label>
      <Button type="button" size="sm" variant="secondary" disabled={busy || (userId === (assignment?.userId ?? '') && teamId === (assignment?.teamId ?? ''))} onClick={() => void save()}>{busy ? 'Saving…' : 'Save assignment'}</Button>
    </> : null}
    {error ? <p role="alert">{error}</p> : null}
  </section>;
}
