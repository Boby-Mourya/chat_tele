import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { MFASecurityPanel } from '@/components/mfa-security-panel';
import { SubscriptionBillingPanel } from '@/components/SubscriptionBillingPanel';
import { Badge, Button, Card, PageLoader } from '@/components/ui';
import { useToast } from '@/components/providers';
import { WorkspaceAPIKeysPanel } from '@/components/WorkspaceAPIKeysPanel';
import { WorkspaceBrandingControlCenter } from '@/features/branding/WorkspaceBrandingControlCenter';
import { workspaceApi, type WorkspaceSettings } from '@/lib/workspace-api';
import { WorkspaceBusinessHoursSettings } from './WorkspaceBusinessHoursSettings';
import { WorkspaceDeveloperSettings } from './WorkspaceDeveloperSettings';
import { WorkspaceGeneralSettings } from './WorkspaceGeneralSettings';
import { WorkspaceMembersSettings } from './WorkspaceMembersSettings';
import { WorkspaceNotificationsSettings } from './WorkspaceNotificationsSettings';
import { WorkspaceRolesSettings } from './WorkspaceRolesSettings';
import { WorkspaceSecuritySettings } from './WorkspaceSecuritySettings';
import { WorkspaceSessionSettings } from './WorkspaceSessionSettings';
import { WorkspaceSettingsNavigation } from './WorkspaceSettingsNavigation';
import { WorkspaceTeamsSettings } from './WorkspaceTeamsSettings';
import {
  workspaceSettingsApi,
  type CapabilityCatalog,
  type SettingsSection,
  type WorkspaceSettingsBundle,
} from './workspaceSettings.api';
import '@/pages/WorkspaceTeam.css';

const sections: SettingsSection[] = [
  'general', 'members', 'teams', 'roles',
  'branding', 'dashboard', 'widget', 'email',
  'channels', 'notifications', 'business-hours',
  'crm', 'integrations', 'webhooks',
  'security', 'mfa', 'sessions', 'audit',
  'developer', 'api-keys', 'oauth-apps', 'api-logs',
  'billing', 'usage',
];
const brandingPermissions = ['branding.view', 'branding.edit', 'branding.publish', 'branding.domain.manage'];
const sectionPermissions: Partial<Record<SettingsSection, string[]>> = {
  general: ['settings.view'], members: ['members.view'], teams: ['teams.manage'], roles: ['roles.manage'],
  branding: brandingPermissions, dashboard: brandingPermissions, widget: brandingPermissions, email: brandingPermissions,
  channels: ['channels.view'], notifications: ['settings.view'], 'business-hours': ['settings.view'],
  crm: ['crm.view', 'crm.manage', 'integrations.view'], integrations: ['integrations.view'], webhooks: ['settings.view', 'integrations.manage'],
  security: ['settings.view'], mfa: ['workspace.view'], sessions: ['settings.view'], audit: ['audit.view'],
  developer: ['settings.view'], 'api-keys': ['api_keys.view', 'api_keys.manage'], 'oauth-apps': ['integrations.view'], 'api-logs': ['settings.view', 'audit.view'],
  billing: ['billing.view'], usage: ['billing.view', 'usage.view'],
};
const emptyCapabilities: CapabilityCatalog = { permissions: [], builtinRoles: {}, resourceKinds: [] };

function canOpenSection(section: SettingsSection, permissions: string[]): boolean {
  const required = sectionPermissions[section] ?? [];
  return required.length === 0 || required.some((permission) => permissions.includes(permission));
}

export function WorkspaceSettingsPage() {
  const { section: rawSection } = useParams();
  const navigate = useNavigate();
  const { pushToast } = useToast();
  // Keep `/apps` as a compatibility alias, while `/integrations` is the
  // canonical workspace settings route from the audit contract.
  const normalized = rawSection === 'apps' ? 'integrations' : rawSection;
  const section = sections.includes(normalized as SettingsSection) ? normalized as SettingsSection : 'general';
  const [workspace, setWorkspace] = useState<WorkspaceSettings | null>(null);
  const [bundle, setBundle] = useState<WorkspaceSettingsBundle | null>(null);
  const [capabilities, setCapabilities] = useState<CapabilityCatalog | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    let current = true;
    workspaceApi.get()
      .then(async (workspaceValue) => {
        const [settingsValue, catalog] = await Promise.all([
          workspaceSettingsApi.get(),
            (workspaceValue.permissions ?? []).includes('roles.manage')
            ? workspaceSettingsApi.capabilities()
            : Promise.resolve(emptyCapabilities),
        ]);
        if (!current) return;
        setWorkspace(workspaceValue);
        setBundle(settingsValue);
        setCapabilities(catalog);
        setError('');
      })
      .catch((reason: unknown) => {
        if (current) setError(reason instanceof Error ? reason.message : 'Workspace settings could not be loaded');
      });
    return () => { current = false; };
  }, []);

  const permissions = workspace?.permissions ?? [];
  const canManage = permissions.includes('settings.manage');
  async function save<T>(work: () => Promise<T>, apply: (value: T) => void, message: string) {
    setSaving(true);
    try {
      const value = await work();
      apply(value);
      pushToast(message);
    } catch (reason) {
      pushToast(reason instanceof Error ? reason.message : 'Settings could not be saved', 'error');
    } finally {
      setSaving(false);
    }
  }

  if (error) return <div className="page"><h2>Workspace settings could not be loaded</h2><p role="alert">{error}</p><Button onClick={() => window.location.reload()}>Retry</Button></div>;
  if (!workspace || !bundle || !capabilities) return <PageLoader />;

  const sectionAllowed = canOpenSection(section, permissions);
  const brandSurface = section === 'dashboard' ? 'dashboard' : section === 'widget' ? 'widget' : section === 'email' ? 'email' : 'identity';

  return <div className="page workspace-console-page">
    <div className="page-heading page-heading--split"><div><span className="page-kicker">Workspace administration</span><h2>Settings</h2><p>Workspace-owned configuration, access, security, developer controls, billing, and white label.</p></div><Badge tone="brand">{workspace.plan} plan</Badge></div>
    <div className="workspace-console-layout">
      <WorkspaceSettingsNavigation active={section} permissions={permissions} onSelect={(next) => navigate(`/workspace/settings/${next}`)} />
      <div className="workspace-console-content">
        {!sectionAllowed ? <Card className="workspace-panel"><div className="workspace-panel__body"><h3>Access unavailable</h3><p>Your current workspace permissions do not allow access to this settings section.</p></div></Card> : null}
        {sectionAllowed && section === 'general' ? <WorkspaceGeneralSettings workspace={workspace} bundle={bundle} disabled={!canManage || saving} onWorkspace={setWorkspace} onBundle={setBundle} onSave={() => void save(
          async () => {
            const updated = await workspaceApi.update({ name: workspace.name, slug: workspace.slug, preferences: workspace.preferences });
            await workspaceSettingsApi.saveGeneral(bundle.general);
            return updated;
          }, setWorkspace, 'Workspace general settings saved')} /> : null}
        {sectionAllowed && section === 'business-hours' ? <WorkspaceBusinessHoursSettings value={bundle.general.businessHours} disabled={!canManage || saving} onChange={(businessHours) => setBundle({ ...bundle, general: { ...bundle.general, businessHours } })} onSave={() => void save(() => workspaceSettingsApi.saveGeneral(bundle.general), (general) => setBundle({ ...bundle, general }), 'Business hours saved')} /> : null}
        {sectionAllowed && section === 'members' ? <WorkspaceMembersSettings workspace={workspace} /> : null}
        {sectionAllowed && section === 'roles' ? <WorkspaceRolesSettings value={bundle.roles} catalog={capabilities} disabled={saving || !permissions.includes('roles.manage')} onChange={(roles) => setBundle({ ...bundle, roles })} onSave={() => void save(() => workspaceSettingsApi.saveRoles(bundle.roles), (roles) => setBundle({ ...bundle, roles }), 'Roles saved')} /> : null}
        {sectionAllowed && section === 'teams' ? <WorkspaceTeamsSettings value={bundle.teams} roles={bundle.roles} disabled={saving || !permissions.includes('teams.manage')} onChange={(teams) => setBundle({ ...bundle, teams })} onSave={() => void save(() => workspaceSettingsApi.saveTeams(bundle.teams), (teams) => setBundle({ ...bundle, teams }), 'Teams saved')} /> : null}
        {sectionAllowed && section === 'security' ? <WorkspaceSecuritySettings bundle={bundle} disabled={!canManage || saving} onBundle={setBundle} onSave={() => void save(() => workspaceSettingsApi.saveSecurity(bundle.security), (security) => setBundle({ ...bundle, security }), 'Security policy saved')} /> : null}
        {sectionAllowed && section === 'mfa' ? <MFASecurityPanel /> : null}
        {sectionAllowed && section === 'sessions' ? <WorkspaceSessionSettings value={bundle.security} disabled={!canManage || saving} onChange={(security) => setBundle({ ...bundle, security })} onSave={() => void save(() => workspaceSettingsApi.saveSecurity(bundle.security), (security) => setBundle({ ...bundle, security }), 'Session policy saved')} /> : null}
        {sectionAllowed && section === 'notifications' ? <WorkspaceNotificationsSettings bundle={bundle} disabled={!canManage || saving} onBundle={setBundle} onSave={() => void save(() => workspaceSettingsApi.saveNotifications(bundle.notifications), (notifications) => setBundle({ ...bundle, notifications }), 'Notification settings saved')} /> : null}
        {sectionAllowed && section === 'channels' ? <LinkSection title="Workspace channels" description="Channel connections remain owned by the existing channel pipeline." href="/integrations" action="Open channels and integrations" /> : null}
        {sectionAllowed && section === 'crm' ? <LinkSection title="CRM integrations" description="CRM connections, mapping, sync and delivery remain in the existing workspace-scoped CRM pipeline." href="/integrations" action="Open CRM integrations" /> : null}
        {sectionAllowed && section === 'integrations' ? <LinkSection title="Workspace integrations" description="Connected applications, OAuth connections, CRM providers, and integration health remain workspace-scoped in one pipeline." href="/integrations" action="Open apps & integrations" /> : null}
        {sectionAllowed && section === 'oauth-apps' ? <LinkSection title="OAuth applications" description="OAuth application and connection credentials are managed by the existing integration pipeline." href="/integrations" action="Open OAuth integrations" /> : null}
        {sectionAllowed && section === 'webhooks' && permissions.includes('settings.view') ? <WorkspaceDeveloperSettings workspace={workspace} bundle={bundle} disabled={!canManage || saving} onBundle={setBundle} onSave={() => void save(() => workspaceSettingsApi.saveDeveloper(bundle.developer), (developer) => setBundle({ ...bundle, developer }), 'Webhook policy saved')} /> : null}
        {sectionAllowed && section === 'webhooks' && !permissions.includes('settings.view') ? <LinkSection title="Webhooks" description="Webhook endpoints and deliveries are managed in the existing integrations pipeline." href="/integrations" action="Open webhooks" /> : null}
        {sectionAllowed && section === 'developer' ? <WorkspaceDeveloperSettings workspace={workspace} bundle={bundle} disabled={!canManage || saving} onBundle={setBundle} onSave={() => void save(() => workspaceSettingsApi.saveDeveloper(bundle.developer), (developer) => setBundle({ ...bundle, developer }), 'Developer policy saved')} /> : null}
        {sectionAllowed && section === 'api-keys' ? <WorkspaceAPIKeysPanel workspace={workspace} /> : null}
        {sectionAllowed && section === 'api-logs' ? <LinkSection title="API and request history" description={`Workspace request-log retention policy is ${bundle.developer.requestLogRetentionDays} days. Operational/audit history remains in the existing audit pipeline.`} href="/audit" action="Open audit / request history" /> : null}
        {sectionAllowed && section === 'audit' ? <LinkSection title="Workspace audit" description="Administrative writes from this settings center are recorded in the existing audit pipeline." href="/audit" action="Open audit log" /> : null}
        {sectionAllowed && (section === 'billing' || section === 'usage') ? <SubscriptionBillingPanel workspace={workspace} /> : null}
        {sectionAllowed && ['branding', 'dashboard', 'widget', 'email'].includes(section) ? <WorkspaceBrandingControlCenter key={brandSurface} initialSurface={brandSurface} bundle={bundle} permissions={permissions} onChange={setBundle} /> : null}
      </div>
    </div>
  </div>;
}

function LinkSection({ title, description, href, action }: { title: string; description: string; href: string; action: string }) {
  return <Card className="workspace-panel"><div className="workspace-panel__body"><h3>{title}</h3><p>{description}</p><a className="button button--primary button--md" href={href}>{action}</a></div></Card>;
}
