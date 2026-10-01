import { useEffect, useState } from 'react';
import { Button, Card, Field } from '@/components/ui';
import { api } from '@/lib/api';
import { workspaceTeamApi, type WorkspaceMember } from '@/lib/workspace-team-api';
import type { Agent } from '@/types';
import type { CapabilityCatalog, CustomRole, RolesSettings } from './workspaceSettings.api';

export function WorkspaceRolesSettings({
  value,
  catalog,
  disabled,
  onChange,
  onSave,
}: {
  value: RolesSettings;
  catalog: CapabilityCatalog;
  disabled: boolean;
  onChange: (value: RolesSettings) => void;
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
      if (current) setError(reason instanceof Error ? reason.message : 'Role resources could not be loaded');
    });
    return () => { current = false; };
  }, []);

  function updateRole(index: number, updater: (role: CustomRole) => CustomRole) {
    onChange({ ...value, customRoles: value.customRoles.map((role, roleIndex) => roleIndex === index ? updater(role) : role) });
  }

  function addRole() {
    onChange({
      ...value,
      customRoles: [...value.customRoles, {
        id: crypto.randomUUID(),
        name: 'Custom role',
        description: '',
        permissions: ['workspace.view'],
        resources: { selected: {}, conversationScope: 'all' },
      }],
    });
  }

  function togglePermission(index: number, permission: string) {
    updateRole(index, (role) => ({
      ...role,
      permissions: role.permissions.includes(permission)
        ? role.permissions.filter((item) => item !== permission)
        : [...role.permissions, permission].sort(),
    }));
  }

  function toggleAgent(index: number, agentId: string) {
    updateRole(index, (role) => {
      const selected = role.resources.selected.agents ?? [];
      const agentsValue = selected.includes(agentId) ? selected.filter((id) => id !== agentId) : [...selected, agentId];
      return { ...role, resources: { ...role.resources, selected: { ...role.resources.selected, agents: agentsValue } } };
    });
  }

  function toggleMemberRole(userId: string, roleId: string) {
    const assigned = value.memberRoleIds[userId] ?? [];
    const next = assigned.includes(roleId) ? assigned.filter((id) => id !== roleId) : [...assigned, roleId];
    const memberRoleIds = { ...value.memberRoleIds };
    if (next.length) memberRoleIds[userId] = next;
    else delete memberRoleIds[userId];
    onChange({ ...value, memberRoleIds });
  }

  return <Card className="workspace-panel">
    <div className="workspace-panel__body">
      <div className="page-heading page-heading--split"><div><h3>Roles & permissions</h3><p>Capabilities are explicit, workspace-scoped grants. Custom roles can further restrict agent and conversation visibility.</p></div><Button disabled={disabled} onClick={addRole}>Add custom role</Button></div>
      {error ? <p role="alert">{error}</p> : null}
      <div className="setup-resource"><strong>Built-in roles</strong>{Object.entries(catalog.builtinRoles).map(([name, permissions]) => <details key={name}><summary>{name.replaceAll('_', ' ')} · {permissions.length} permissions</summary><p>{permissions.join(', ')}</p></details>)}</div>
      {value.customRoles.length === 0 ? <p>No custom roles. Built-in roles continue to use the existing access policy.</p> : null}
      {value.customRoles.map((role, index) => <div className="setup-resource" key={role.id}>
        <div className="two-fields"><Field label="Role name"><input disabled={disabled} value={role.name} onChange={(event) => updateRole(index, (current) => ({ ...current, name: event.target.value }))} /></Field><Field label="Conversation scope"><select disabled={disabled} value={role.resources.conversationScope} onChange={(event) => updateRole(index, (current) => ({ ...current, resources: { ...current.resources, conversationScope: event.target.value as 'all' | 'assigned' | 'team' } }))}><option value="all">All conversations</option><option value="team">Team conversations</option><option value="assigned">Assigned conversations</option></select></Field></div>
        <Field label="Description"><input disabled={disabled} value={role.description} onChange={(event) => updateRole(index, (current) => ({ ...current, description: event.target.value }))} /></Field>
        <strong>Permissions</strong>
        <div className="workspace-agent-scope__list">{catalog.permissions.map((permission) => <label key={permission}><input type="checkbox" disabled={disabled || (permission === 'workspace.view' && role.permissions.includes(permission) && role.permissions.length === 1)} checked={role.permissions.includes(permission)} onChange={() => togglePermission(index, permission)} /><span>{permission}</span></label>)}</div>
        <strong>Agent resource scope</strong><p>Leave all agents unchecked to keep the member's existing workspace-level agent scope. Selecting agents can only narrow access.</p>
        <div className="workspace-agent-scope__list">{agents.map((agent) => <label key={agent.id}><input type="checkbox" disabled={disabled} checked={(role.resources.selected.agents ?? []).includes(agent.id)} onChange={() => toggleAgent(index, agent.id)} /><span>{agent.name}</span></label>)}</div>
        <Button variant="danger" disabled={disabled} onClick={() => {
          const customRoles = value.customRoles.filter((_, roleIndex) => roleIndex !== index);
          const memberRoleIds = Object.fromEntries(Object.entries(value.memberRoleIds).reduce<Array<[string, string[]]>>((entries, [userId, rawIds]) => {
            const ids = (rawIds ?? []).filter((id) => id !== role.id);
            if (ids.length) entries.push([userId, ids]);
            return entries;
          }, []));
          onChange({ customRoles, memberRoleIds });
        }}>Delete role</Button>
      </div>)}
      <div className="setup-resource"><strong>Member custom-role assignments</strong><p>Built-in workspace roles remain intact; these assignments add only the validated custom capabilities above.</p>
        {members.map((member) => <div key={member.userId}><strong>{member.name}</strong><small>{member.email} · built-in {member.role.replaceAll('_', ' ')}</small><div className="workspace-agent-scope__list">{value.customRoles.map((role) => <label key={role.id}><input type="checkbox" disabled={disabled} checked={(value.memberRoleIds[member.userId] ?? []).includes(role.id)} onChange={() => toggleMemberRole(member.userId, role.id)} /><span>{role.name}</span></label>)}</div></div>)}
      </div>
      <div className="workspace-panel__actions"><Button disabled={disabled || value.customRoles.some((role) => role.permissions.length === 0)} onClick={onSave}>Save roles</Button></div>
    </div>
  </Card>;
}
