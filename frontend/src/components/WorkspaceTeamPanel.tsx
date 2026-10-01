import { CircleAlert, Clock3, Mail, Pencil, RefreshCw, ShieldCheck, Trash2, UserPlus, UsersRound } from 'lucide-react';
import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import { useToast } from '@/components/providers';
import { Badge, Button, Card, Field, Modal, Switch } from '@/components/ui';
import { api } from '@/lib/api';
import { invitationDeliveryNotice, workspaceTeamApi, type WorkspaceAccessInput, type WorkspaceInvitation, type WorkspaceMember, type WorkspaceRole } from '@/lib/workspace-team-api';
import { workspacePresentationKey, type WorkspaceSettings } from '@/lib/workspace-api';
import type { Agent } from '@/types';

const ROLE_OPTIONS: Array<{ value: WorkspaceRole; label: string }> = [
  { value: 'workspace_admin', label: 'Workspace admin' }, { value: 'manager', label: 'Manager' },
  { value: 'operator', label: 'Operator' }, { value: 'analyst', label: 'Analyst' }, { value: 'viewer', label: 'Viewer' },
];
const emptyAccess: WorkspaceAccessInput = { role: 'operator', allAgentsAccess: true, agentIds: [] };
function roleLabel(role: WorkspaceRole): string { return ROLE_OPTIONS.find((item) => item.value === role)?.label ?? role; }

export function WorkspaceTeamPanel({ workspace }: { workspace: WorkspaceSettings }) {
  // A new account/workspace/capability snapshot gets a separate editor instance.
  const context = `${workspacePresentationKey()}:${workspace.id}:${[...(workspace.permissions ?? [])].sort().join(',')}`;
  return <TeamPanel key={context} workspace={workspace} />;
}

function TeamPanel({ workspace }: { workspace: WorkspaceSettings }) {
  const { pushToast } = useToast();
  const [members, setMembers] = useState<WorkspaceMember[]>([]);
  const [invitations, setInvitations] = useState<WorkspaceInvitation[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [actionError, setActionError] = useState('');
  const [inviteOpen, setInviteOpen] = useState(false);
  const [email, setEmail] = useState('');
  const [inviteDraft, setInviteDraft] = useState<WorkspaceAccessInput>(emptyAccess);
  const [editing, setEditing] = useState<WorkspaceMember | null>(null);
  const [editDraft, setEditDraft] = useState<WorkspaceAccessInput>(emptyAccess);
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const alive = useRef(true);
  const sequence = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const permissions = workspace.permissions ?? [];
  const canView = permissions.includes('members.view');
  const canManage = permissions.includes('members.manage');
  const canInvite = canManage && permissions.includes('members.invite');

  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; controller.current?.abort(); sequence.current += 1; };
  }, []);
  const self = members.find((member) => member.isSelf);
  const canGrantAll = self?.allAgentsAccess === true;
  const managesScope = (value: { allAgentsAccess: boolean; agentIds: string[] }) =>
    !!self && (self.allAgentsAccess || (!value.allAgentsAccess && value.agentIds.every((id) => self.agentIds.includes(id))));

  const load = useCallback(async () => {
    const generation = ++sequence.current;
    controller.current?.abort();
    if (!canView) { setLoadError('Your current role cannot view team membership.'); setLoading(false); return; }
    const request = new AbortController(); controller.current = request;
    setLoading(true); setLoadError('');
    try {
      const [nextMembers, nextInvitations, nextAgents] = await Promise.all([
        workspaceTeamApi.listMembers(request.signal), workspaceTeamApi.listInvitations(request.signal),
        canManage ? api.agents.list() : Promise.resolve([] as Agent[]),
      ]);
      if (!alive.current || request.signal.aborted || generation !== sequence.current) return;
      setMembers(nextMembers); setInvitations(nextInvitations); setAgents(nextAgents);
    } catch (error) {
      if (alive.current && !request.signal.aborted && generation === sequence.current) {
        setMembers([]); setInvitations([]); setAgents([]);
        setLoadError(error instanceof Error ? error.message : 'Team membership could not be loaded');
      }
    } finally { if (alive.current && generation === sequence.current) setLoading(false); }
  }, [canManage, canView]);
  useEffect(() => { void load(); }, [load]);

  async function mutate(action: () => Promise<void>) {
    if (busyRef.current) return;
    busyRef.current = true; setBusy(true); setActionError('');
    try { await action(); }
    catch (error) {
      if (alive.current) {
        const message = error instanceof Error ? error.message : 'The change could not be confirmed';
        setActionError(message); pushToast(message, 'error');
      }
    } finally { busyRef.current = false; if (alive.current) setBusy(false); }
  }
  function notifyInvitation(value: WorkspaceInvitation) {
    const notice = invitationDeliveryNotice(value);
    pushToast(notice.message, notice.tone);
  }
  function openEdit(member: WorkspaceMember) {
    setEditing(member); setActionError('');
    setEditDraft({ role: member.role, allAgentsAccess: member.allAgentsAccess, agentIds: [...member.agentIds] });
  }
  async function submitInvitation(event: FormEvent) {
    event.preventDefault(); if (!canInvite) return;
    await mutate(async () => {
      const invitation = await workspaceTeamApi.invite({ ...inviteDraft, email: email.trim().toLowerCase() });
      if (!alive.current) return;
      setInvitations((old) => [invitation, ...old.filter((item) => item.id !== invitation.id)]);
      setEmail(''); setInviteDraft(emptyAccess); setInviteOpen(false); notifyInvitation(invitation);
    });
  }
  async function saveMember(event: FormEvent) {
    event.preventDefault(); if (!canManage || !editing) return;
    const target = editing;
    await mutate(async () => {
      const updated = await workspaceTeamApi.updateMember(target.userId, editDraft);
      if (!alive.current) return;
      setMembers((old) => old.map((item) => item.userId === updated.userId ? updated : item));
      setEditing(null); pushToast(`${updated.name}'s access was updated`);
    });
  }
  function remove(member: WorkspaceMember) {
    if (!canManage || member.isSelf || !window.confirm(`Remove ${member.name} from ${workspace.name}?`)) return;
    void mutate(async () => {
      await workspaceTeamApi.removeMember(member.userId);
      if (!alive.current) return;
      setMembers((old) => old.filter((item) => item.userId !== member.userId));
      pushToast(`${member.name} was removed from this workspace`);
    });
  }
  function resend(invitation: WorkspaceInvitation) {
    if (!canInvite) return;
    void mutate(async () => {
      const updated = await workspaceTeamApi.resendInvitation(invitation.id);
      if (!alive.current) return;
      setInvitations((old) => old.map((item) => item.id === updated.id ? updated : item)); notifyInvitation(updated);
    });
  }
  function revoke(invitation: WorkspaceInvitation) {
    if (!canManage || !window.confirm(`Revoke the invitation for ${invitation.email}?`)) return;
    void mutate(async () => {
      await workspaceTeamApi.revokeInvitation(invitation.id);
      if (!alive.current) return;
      setInvitations((old) => old.map((item) => item.id === invitation.id ? { ...item, status: 'revoked' } : item));
      pushToast(`Invitation for ${invitation.email} was revoked`);
    });
  }
  function reload() { setEditing(null); setActionError(''); void load(); }

  return <>
    <Card className="workspace-panel">
      <div className="workspace-panel__heading"><span><UsersRound /></span><div><h3>Team members</h3><p>Manage staff roles and selected-agent access in this workspace.</p></div>
        {canInvite ? <Button icon={UserPlus} disabled={busy || loading} onClick={() => { setInviteDraft({ ...emptyAccess, allAgentsAccess: canGrantAll }); setActionError(''); setInviteOpen(true); }}>Invite member</Button> : null}
      </div>
      {actionError ? <div role="alert" className="workspace-team-state"><p>{actionError}</p><Button variant="secondary" disabled={busy} onClick={reload}>Reload and review team</Button></div> : null}
      {loading ? <div className="workspace-team-state" role="status">Loading team access…</div> : loadError ?
        <div className="workspace-team-state" role="alert"><CircleAlert /><h4>Team access unavailable</h4><p>{loadError}</p>{canView ? <Button onClick={() => void load()}>Try again</Button> : null}</div> : <>
          <section className="workspace-team-section"><div className="workspace-team-section__heading"><strong>Active members</strong><small>{members.length} members</small></div>
            <div className="workspace-member-list">{members.map((member) => <div key={member.userId}>
              <span className="mini-avatar">{member.name.charAt(0).toUpperCase()}</span>
              <span><strong>{member.name}{member.isSelf ? ' (you)' : ''}</strong><small>{member.email} · {member.allAgentsAccess ? 'All current and future agents' : `${member.agentIds.length} selected agents`}</small></span>
              <Badge tone="success">Active</Badge><Badge tone={member.role === 'workspace_admin' ? 'purple' : 'neutral'}>{roleLabel(member.role)}</Badge>
              {canManage && !member.isSelf && managesScope(member) ? <span className="workspace-member-list__actions"><Button size="sm" variant="ghost" icon={Pencil} disabled={busy} onClick={() => openEdit(member)}>Edit</Button>
                <button type="button" className="icon-button danger-hover" disabled={busy} onClick={() => remove(member)} aria-label={`Remove ${member.name}`}><Trash2 /></button></span> : null}
            </div>)}</div>
          </section>
          <section className="workspace-team-section"><div className="workspace-team-section__heading"><span><Mail /><strong>Invitations</strong></span></div>
            <div className="workspace-member-list">{invitations.filter((item) => item.status !== 'accepted').map((invitation) => <div key={invitation.id}>
              <span className="mini-avatar">{invitation.email.charAt(0).toUpperCase()}</span><span><strong>{invitation.email}</strong>
                <small>{invitation.deliveryState === 'failed' ? 'Delivery failed — invitation saved' : invitation.deliveryState === 'sent' ? 'Email sent' : 'Email delivery not confirmed'}</small></span>
              <span className="workspace-invitation-expiry"><Clock3 />{new Date(invitation.expiresAt).toLocaleDateString()}</span>
              <Badge tone={invitation.status === 'pending' ? 'warning' : 'danger'}>{invitation.status}</Badge><Badge>{roleLabel(invitation.role)}</Badge>
              {canManage && managesScope(invitation) && ['pending', 'expired'].includes(invitation.status) ? <span className="workspace-member-list__actions">
                {canInvite ? <Button size="sm" variant="ghost" icon={RefreshCw} disabled={busy} onClick={() => resend(invitation)}>Resend</Button> : null}
                <button type="button" className="icon-button danger-hover" disabled={busy} onClick={() => revoke(invitation)} aria-label={`Revoke invitation for ${invitation.email}`}><Trash2 /></button>
              </span> : null}
            </div>)}</div>{invitations.length === 0 ? <p className="workspace-team-state">No invitations.</p> : null}
          </section>
        </>}
    </Card>
    <Modal open={inviteOpen} onClose={() => !busy && setInviteOpen(false)} title="Invite a team member" closeDisabled={busy}
      description="The invited user receives only this workspace role and selected-agent scope."
      footer={<><Button variant="secondary" disabled={busy} onClick={() => setInviteOpen(false)}>Cancel</Button><Button type="submit" form="workspace-team-invite-form" disabled={busy || !canInvite}>{busy ? 'Submitting…' : 'Send invitation'}</Button></>}>
      {actionError ? <p role="alert">{actionError}</p> : null}
      <form id="workspace-team-invite-form" className="workspace-access-form" onSubmit={(event) => void submitInvitation(event)}>
        <Field label="Email address"><input type="email" required value={email} disabled={busy} onChange={(event) => setEmail(event.target.value)} autoComplete="email" /></Field>
        <AccessEditor draft={inviteDraft} onChange={setInviteDraft} agents={agents} disabled={busy} canGrantAll={canGrantAll} />
        <div className="workspace-access-note"><ShieldCheck /><span>The invited user must accept with the invited email address. The backend determines their workspace access.</span></div>
      </form>
    </Modal>
    <Modal open={editing !== null} onClose={() => !busy && setEditing(null)} title="Edit member access" closeDisabled={busy}
      description={editing ? `Review access for ${editing.email}. Server errors remain visible so you can review and retry explicitly.` : undefined}
      footer={<><Button variant="secondary" disabled={busy} onClick={() => setEditing(null)}>Cancel</Button><Button type="submit" form="workspace-member-edit-form" disabled={busy || !canManage}>{busy ? 'Saving…' : 'Save access'}</Button></>}>
      {actionError ? <div role="alert"><p>{actionError}</p><Button variant="secondary" disabled={busy} onClick={reload}>Discard draft and reload team</Button></div> : null}
      <form id="workspace-member-edit-form" className="workspace-access-form" onSubmit={(event) => void saveMember(event)}>
        <AccessEditor draft={editDraft} onChange={setEditDraft} agents={agents} disabled={busy} canGrantAll={canGrantAll} />
      </form>
    </Modal>
  </>;
}

function AccessEditor({ draft, onChange, agents, disabled, canGrantAll }: {
  draft: WorkspaceAccessInput; onChange: (value: WorkspaceAccessInput) => void; agents: Agent[]; disabled: boolean; canGrantAll: boolean;
}) {
  return <>
    <Field label="Workspace role"><select value={draft.role} disabled={disabled} onChange={(event) => onChange({ ...draft, role: event.target.value as WorkspaceRole })}>
      {ROLE_OPTIONS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
    </select></Field>
    <Switch checked={draft.allAgentsAccess} disabled={disabled || !canGrantAll} label="Access all agents" description="Includes future agents. Disable to allow only the selected agents; an empty selection gives no agent access."
      onChange={(checked) => onChange({ ...draft, allAgentsAccess: checked, agentIds: checked ? [] : draft.agentIds })} />
    {!draft.allAgentsAccess ? <div className="workspace-agent-scope"><strong>Allowed agents</strong><div className="workspace-agent-scope__list">
      {agents.map((agent) => <label key={agent.id}><input type="checkbox" disabled={disabled} checked={draft.agentIds.includes(agent.id)}
        onChange={() => onChange({ ...draft, agentIds: draft.agentIds.includes(agent.id) ? draft.agentIds.filter((id) => id !== agent.id) : [...draft.agentIds, agent.id] })} /><span>{agent.name}</span></label>)}
      {agents.length === 0 ? <p>No agents are available.</p> : null}
    </div></div> : null}
  </>;
}
