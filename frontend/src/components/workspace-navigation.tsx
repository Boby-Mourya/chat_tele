import { Building2, CreditCard, ExternalLink, KeyRound, Palette, Settings2, ShieldCheck, UsersRound } from 'lucide-react';

export const workspaceSections = [
  { id: 'workspace', label: 'Workspace', icon: Building2 },
  { id: 'team', label: 'Team members', icon: UsersRound },
  { id: 'developer', label: 'API keys', icon: KeyRound },
  { id: 'security', label: 'Security', icon: ShieldCheck },
  { id: 'billing', label: 'Billing', icon: CreditCard },
] as const;

export function WorkspaceNavigation({ active, onSelect }: { active: string; onSelect: (id: string) => void }) {
  return <nav className="workspace-console-nav" aria-label="Workspace settings">
    <p>Workspace</p>
    {workspaceSections.map(({ id, label, icon: Icon }) => <button type="button" key={id} className={active === id ? 'is-active' : ''} onClick={() => onSelect(id)}><Icon /><span>{label}</span></button>)}
    <a href="/workspace/settings/general"><Settings2 /><span>Settings center</span></a>
    <p>Brand</p>
    <a className={active === 'white-label' ? 'is-active' : ''} href="/workspace/white-label" target="_blank" rel="noopener noreferrer"><Palette /><span>White Label (legacy)</span><ExternalLink /></a>
    <a href="/workspace/settings/branding"><Palette /><span>White label center</span></a>
  </nav>;
}
