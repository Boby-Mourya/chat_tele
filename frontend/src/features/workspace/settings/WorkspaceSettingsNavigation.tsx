import {
  Bell, Blocks, Braces, Building2, CreditCard, Gauge, KeyRound, LayoutDashboard,
  Mail, Palette, Radio, ScrollText, ShieldCheck, UsersRound, UserRoundCog,
} from 'lucide-react';
import type { SettingsSection } from './workspaceSettings.api';

type Item = { id: SettingsSection; label: string; icon: typeof Building2; permissions?: string[] };
const brandPermissions = ['branding.view', 'branding.edit', 'branding.publish', 'branding.domain.manage'];
const groups: { label: string; items: Item[] }[] = [
  { label: 'Workspace', items: [
    { id: 'general', label: 'General', icon: Building2, permissions: ['settings.view'] },
    { id: 'members', label: 'Members', icon: UsersRound, permissions: ['members.view'] },
    { id: 'teams', label: 'Teams', icon: UsersRound, permissions: ['teams.manage'] },
    { id: 'roles', label: 'Roles & permissions', icon: UserRoundCog, permissions: ['roles.manage'] },
  ] },
  { label: 'Customization', items: [
    { id: 'branding', label: 'White label', icon: Palette, permissions: brandPermissions },
    { id: 'dashboard', label: 'Dashboard', icon: LayoutDashboard, permissions: brandPermissions },
    { id: 'widget', label: 'Widget', icon: Blocks, permissions: brandPermissions },
    { id: 'email', label: 'Email', icon: Mail, permissions: brandPermissions },
  ] },
  { label: 'Communication', items: [
    { id: 'channels', label: 'Channels', icon: Radio, permissions: ['channels.view'] },
    { id: 'notifications', label: 'Notifications', icon: Bell, permissions: ['settings.view'] },
    { id: 'business-hours', label: 'Business hours', icon: Gauge, permissions: ['settings.view'] },
  ] },
  { label: 'Integrations', items: [
    { id: 'crm', label: 'CRM', icon: Blocks, permissions: ['crm.view', 'crm.manage', 'integrations.view'] },
    { id: 'integrations', label: 'Apps & integrations', icon: Blocks, permissions: ['integrations.view'] },
    { id: 'webhooks', label: 'Webhooks', icon: Braces, permissions: ['settings.view', 'integrations.manage'] },
  ] },
  { label: 'Security', items: [
    { id: 'security', label: 'Authentication', icon: ShieldCheck, permissions: ['settings.view'] },
    { id: 'mfa', label: 'MFA', icon: KeyRound, permissions: ['workspace.view'] },
    { id: 'sessions', label: 'Sessions', icon: ShieldCheck, permissions: ['settings.view'] },
    { id: 'audit', label: 'Audit', icon: ScrollText, permissions: ['audit.view'] },
  ] },
  { label: 'Developer', items: [
    { id: 'api-keys', label: 'API keys', icon: KeyRound, permissions: ['api_keys.view', 'api_keys.manage'] },
    { id: 'oauth-apps', label: 'OAuth apps', icon: Blocks, permissions: ['integrations.view'] },
    { id: 'api-logs', label: 'API logs', icon: Braces, permissions: ['settings.view', 'audit.view'] },
  ] },
  { label: 'Account', items: [
    { id: 'billing', label: 'Billing', icon: CreditCard, permissions: ['billing.view'] },
    { id: 'usage', label: 'Usage', icon: Gauge, permissions: ['billing.view', 'usage.view'] },
  ] },
];

export function WorkspaceSettingsNavigation({ active, onSelect, permissions }: { active: SettingsSection; onSelect: (section: SettingsSection) => void; permissions: string[] }) {
  const allowed = new Set(permissions);
  return <nav className="workspace-console-nav" aria-label="Workspace settings">
    {groups.map((group) => {
      const items = group.items.filter((item) => !item.permissions?.length || item.permissions.some((permission) => allowed.has(permission)));
      if (!items.length) return null;
      return <div key={group.label}><p>{group.label}</p>{items.map(({ id, label, icon: Icon }) =>
        <button type="button" key={id} className={active === id ? 'is-active' : ''} onClick={() => onSelect(id)}><Icon /><span>{label}</span></button>)}</div>;
    })}
  </nav>;
}
