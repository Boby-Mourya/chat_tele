import { useEffect, useState } from 'react';
import { Button, Card, Field, Switch } from '@/components/ui';
import { api } from '@/lib/api';
import { workspaceTeamApi, type WorkspaceMember } from '@/lib/workspace-team-api';
import type { Agent } from '@/types';
import type { BusinessHours, RolesSettings, TeamsSettings, WorkspaceTeam } from './workspaceSettings.api';

const DAYS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'] as const;
const emptyHours = (): BusinessHours => ({ enabled: false, timezone: 'Asia/Kolkata', schedule: {} });
const splitIds = (value: string) => value.split(',').map((item) => item.trim()).filter(Boolean);

export function WorkspaceTeamsSettings({
  value,
  roles,
  disabled,
  onChange,
  onSave,
}: {
  value: TeamsSettings;
  roles: RolesSettings;
  disabled: boolean;
  onChange: (value: TeamsSettings) => void;
  onSave: () => void;
}) {
  const [members, setMembers] = useState<WorkspaceMember[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [error, setError] = useState('');

  useEffect(() => {
    let current = true;
    Promise.all([workspaceTeamApi.listMembers(), api.agents.list()]).then(([memberValues, agentValues]) => {
      if (!current) return;
      setMembers(memberValues);
      setAgents(agentValues);
      setError('');
    }).catch((reason: unknown) => {
      if (current) setError(reason instanceof Error ? reason.message : 'Team resources could not be loaded');
    });
    return () => { current = false; };
  }, []);

  function updateTeam(index: number, updater: (team: WorkspaceTeam) => WorkspaceTeam) {
    onChange({ teams: value.teams.map((team, teamIndex) => teamIndex === index ? updater(team) : team) });
  }

  function toggleList(index: number, key: 'memberIds' | 'managerIds' | 'roleIds' | 'agentIds', id: string) {
    updateTeam(index, (team) => {
      const current = team[key];
      const next = current.includes(id) ? current.filter((valueId) => valueId !== id) : [...current, id];
      if (key === 'memberIds' && !next.includes(id)) {
        return { ...team, memberIds: next, managerIds: team.managerIds.filter((managerId) => managerId !== id) };
      }
      if (key === 'managerIds' && !team.memberIds.includes(id) && !current.includes(id)) {
        return { ...team, memberIds: [...team.memberIds, id], managerIds: next };
      }
      return { ...team, [key]: next };
    });
  }

  function setSchedule(index: number, day: string, range: string) {
    updateTeam(index, (team) => {
      const schedule = { ...team.businessHours.schedule };
      if (range.trim()) schedule[day] = [range.trim()];
      else delete schedule[day];
      return { ...team, businessHours: { ...team.businessHours, schedule } };
    });
  }

  return <Card className="workspace-panel"><div className="workspace-panel__body">
    <div className="page-heading page-heading--split"><div><h3>Teams</h3><p>Teams own membership, managers, roles, queues, agents, channels, business hours, routing context, and escalation rules.</p></div><Button disabled={disabled} onClick={() => onChange({ teams: [...value.teams, { id: crypto.randomUUID(), name: 'New team', description: '', memberIds: [], managerIds: [], roleIds: [], queueIds: [], agentIds: [], channelIds: [], businessHours: emptyHours(), escalationRule: '' }] })}>Add team</Button></div>
    {error ? <p role="alert">{error}</p> : null}
    {value.teams.length === 0 ? <p>No teams yet.</p> : null}
    {value.teams.map((team, index) => <div className="setup-resource" key={team.id}>
      <div className="two-fields"><Field label="Team name"><input disabled={disabled} value={team.name} onChange={(event) => updateTeam(index, (current) => ({ ...current, name: event.target.value }))} /></Field><Field label="Description"><input disabled={disabled} value={team.description} onChange={(event) => updateTeam(index, (current) => ({ ...current, description: event.target.value }))} /></Field></div>
      <strong>Members</strong><div className="workspace-agent-scope__list">{members.map((member) => <label key={member.userId}><input type="checkbox" disabled={disabled} checked={team.memberIds.includes(member.userId)} onChange={() => toggleList(index, 'memberIds', member.userId)} /><span>{member.name} · {member.email}</span></label>)}</div>
      <strong>Managers</strong><div className="workspace-agent-scope__list">{members.map((member) => <label key={member.userId}><input type="checkbox" disabled={disabled} checked={team.managerIds.includes(member.userId)} onChange={() => toggleList(index, 'managerIds', member.userId)} /><span>{member.name}</span></label>)}</div>
      <strong>Custom roles</strong><div className="workspace-agent-scope__list">{roles.customRoles.map((role) => <label key={role.id}><input type="checkbox" disabled={disabled} checked={team.roleIds.includes(role.id)} onChange={() => toggleList(index, 'roleIds', role.id)} /><span>{role.name}</span></label>)}</div>
      <strong>Agents</strong><div className="workspace-agent-scope__list">{agents.map((agent) => <label key={agent.id}><input type="checkbox" disabled={disabled} checked={team.agentIds.includes(agent.id)} onChange={() => toggleList(index, 'agentIds', agent.id)} /><span>{agent.name}</span></label>)}</div>
      <div className="two-fields"><Field label="Queue IDs"><input disabled={disabled} value={team.queueIds.join(', ')} placeholder="Existing queue identifiers" onChange={(event) => updateTeam(index, (current) => ({ ...current, queueIds: splitIds(event.target.value) }))} /></Field><Field label="Channel IDs"><input disabled={disabled} value={team.channelIds.join(', ')} placeholder="Existing channel connection identifiers" onChange={(event) => updateTeam(index, (current) => ({ ...current, channelIds: splitIds(event.target.value) }))} /></Field></div>
      <Field label="Escalation / routing rule"><textarea disabled={disabled} value={team.escalationRule} placeholder="Example: Admissions conversations route here; escalate after 15 minutes." onChange={(event) => updateTeam(index, (current) => ({ ...current, escalationRule: event.target.value }))} /></Field>
      <Switch checked={team.businessHours.enabled} disabled={disabled} onChange={(enabled) => updateTeam(index, (current) => ({ ...current, businessHours: { ...current.businessHours, enabled } }))} label="Team business hours" />
      {team.businessHours.enabled ? <div><Field label="Business-hours timezone"><input disabled={disabled} value={team.businessHours.timezone} onChange={(event) => updateTeam(index, (current) => ({ ...current, businessHours: { ...current.businessHours, timezone: event.target.value } }))} /></Field>{DAYS.map((day) => <Field key={day} label={day.charAt(0).toUpperCase() + day.slice(1)}><input disabled={disabled} value={team.businessHours.schedule[day]?.[0] ?? ''} placeholder="09:00-17:00" onChange={(event) => setSchedule(index, day, event.target.value)} /></Field>)}</div> : null}
      <Button variant="danger" disabled={disabled} onClick={() => onChange({ teams: value.teams.filter((_, teamIndex) => teamIndex !== index) })}>Delete team</Button>
    </div>)}
    <div className="workspace-panel__actions"><Button disabled={disabled} onClick={onSave}>Save teams</Button></div>
  </div></Card>;
}
