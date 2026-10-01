import {
  BarChart3, Building2, Check, ChevronDown, CircleHelp, ClipboardList, Code2, Command, ContactRound, FileSpreadsheet, GraduationCap, History, Inbox,
  LayoutDashboard, LogOut, PanelLeftClose, PanelLeftOpen, PlugZap, Plus, Search, Settings2, ShieldCheck, Sparkles, UsersRound, X,
} from 'lucide-react';
import { useEffect, useMemo, useState, type FormEvent } from 'react';
import { Link, NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { Brand } from '@/components/brand';
import { CommandPalette } from '@/components/CommandPalette';
import { NotificationBell } from '@/components/NotificationBell';
import { useAuth, useToast, useWorkspace } from '@/components/providers';
import { platformAdminApi } from '@/lib/platform-admin-api';

const navigation = [
  { to: '/', label: 'Overview', icon: LayoutDashboard, end: true },
  { to: '/agents', label: 'Agents', icon: Sparkles },
  { to: '/education/courses', label: 'Courses', icon: GraduationCap },
  { to: '/education/batches', label: 'Batches', icon: GraduationCap },
  { to: '/education/students', label: 'Students', icon: UsersRound, end: true },
  { to: '/education/enrollments', label: 'Enrollments', icon: ClipboardList },
  { to: '/education/students/import', label: 'Imports', icon: FileSpreadsheet },
  { to: '/education/access-requests', label: 'Access Requests', icon: ShieldCheck },
  { to: '/education/activity', label: 'Activity', icon: History },
  { to: '/conversations', label: 'Conversations', icon: Inbox },
  { to: '/leads', label: 'Leads', icon: ContactRound },
  { to: '/crm-workflow', label: 'CRM Workflow', icon: PlugZap },
  { to: '/analytics', label: 'Analytics', icon: BarChart3 },
  { to: '/audit', label: 'Audit', icon: ShieldCheck },
  { to: '/integrations', label: 'Integrations', icon: PlugZap },
  { to: '/deploy', label: 'Deploy', icon: Code2 },
];

function pageTitle(pathname: string): string {
  if (pathname === '/') return 'Overview';
  if (pathname.startsWith('/platform-admin')) return 'Platform Control Plane';
  if (pathname.startsWith('/workspace/white-label')) return 'White Label';
  if (pathname.startsWith('/workspace')) return 'Workspace';
  if (pathname.startsWith('/help')) return 'Help Center';
  if (pathname.startsWith('/agents/') && pathname !== '/agents/new') return 'Agent workspace';
  if (pathname.startsWith('/education/students/import')) return 'Imports';
  const item = navigation.find((nav) => nav.to !== '/' && pathname.startsWith(nav.to));
  return item?.label ?? 'Workspace';
}

export function AppShell() {
  const [expanded, setExpanded] = useState(false);
  const [accountOpen, setAccountOpen] = useState(false);
  const [workspaceOpen, setWorkspaceOpen] = useState(false);
  const [commandOpen, setCommandOpen] = useState(false);
  const [creatingWorkspace, setCreatingWorkspace] = useState(false);
  const [workspaceName, setWorkspaceName] = useState('');
  const [workspaceSlug, setWorkspaceSlug] = useState('');
  const [platformAdmin, setPlatformAdmin] = useState(false);
  const { session, logout } = useAuth();
  const { pushToast } = useToast();
  const { workspaces, activeWorkspace, loading, selectWorkspace, createWorkspace } = useWorkspace();
  const location = useLocation(); const navigate = useNavigate();
  const initials = useMemo(() => (session?.user.name || 'NS').split(' ').map((item) => item[0]).join('').slice(0, 2).toUpperCase(), [session]);
  const canViewAudit = Boolean(
    session?.user.role === 'owner'
    || session?.user.role === 'admin'
    || session?.user.role === 'security_admin'
    || activeWorkspace?.permissions?.includes('*')
    || activeWorkspace?.permissions?.includes('audit.view'),
  );
  const visibleNavigation = navigation.filter((item) => item.to !== '/audit' || canViewAudit);
  const mobileNavigation = visibleNavigation.filter((item) => (
    item.to !== '/education/enrollments'
    && item.to !== '/education/students/import'
    && item.to !== '/education/access-requests'
    && item.to !== '/education/activity'
  )).slice(0, 6);

  useEffect(() => {
    let active = true;
    if (!session) {
      setPlatformAdmin(false);
      return () => { active = false; };
    }
    void platformAdminApi.canAccess()
      .then((allowed) => { if (active) setPlatformAdmin(allowed); })
      .catch(() => { if (active) setPlatformAdmin(false); });
    return () => { active = false; };
  }, [session?.accessToken, session?.user.email]);

  useEffect(() => {
    const handleCommandShortcut = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        setCommandOpen((value) => !value);
      }
    };
    window.addEventListener('keydown', handleCommandShortcut);
    return () => window.removeEventListener('keydown', handleCommandShortcut);
  }, []);

  const submitWorkspace = async (event: FormEvent) => {
    event.preventDefault();
    const name = workspaceName.trim();
    const slug = workspaceSlug.trim().toLowerCase().replace(/[^a-z0-9-]/g, '');
    if (name.length < 2 || slug.length < 2) return;
    try {
      await createWorkspace({ name, slug });
      setCreatingWorkspace(false); setWorkspaceOpen(false); setWorkspaceName(''); setWorkspaceSlug('');
      pushToast('Workspace created');
    } catch (error) {
      pushToast(error instanceof Error ? error.message : 'Workspace could not be created', 'error');
    }
  };
  return <div className={`app-shell ${expanded ? 'app-shell--expanded' : ''}`}>
    <aside className="rail" aria-label="Primary navigation">
      <Link to="/" className="rail__brand" aria-label="Northstar AI home"><Brand compact /></Link>
      <nav className="rail__nav">
        {visibleNavigation.map(({ to, label, icon: Icon, end }) => <NavLink key={to} to={to} end={end} className={({ isActive }) => `rail-link ${isActive ? 'is-active' : ''}`} title={label}><Icon /><span>{label}</span></NavLink>)}
      </nav>
      <div className="rail__bottom">
        <NavLink to="/workspace" className={({ isActive }) => `rail-link ${isActive ? 'is-active' : ''}`} title="Workspace"><Settings2 /><span>Workspace</span></NavLink>
        <NavLink to="/help" className={({ isActive }) => `rail-link ${isActive ? 'is-active' : ''}`} title="Help"><CircleHelp /><span>Help</span></NavLink>
        <button className="rail-link rail-toggle" onClick={() => setExpanded((value) => !value)} title={expanded ? 'Collapse sidebar' : 'Expand sidebar'}>{expanded ? <PanelLeftClose /> : <PanelLeftOpen />}<span>{expanded ? 'Collapse' : 'Expand'}</span></button>
      </div>
    </aside>
    <div className="app-main">
      <header className="topbar">
        <div className="topbar__left">
          <div className="mobile-brand"><Brand /></div>
          <div className="workspace-switcher">
            <button className="workspace-switcher__button" type="button" onClick={() => setWorkspaceOpen((value) => !value)} aria-expanded={workspaceOpen} aria-haspopup="menu">
              <span className="workspace-switcher__mark"><Building2 /></span>
              <span><small>Workspace</small><strong>{loading ? 'Loading…' : activeWorkspace?.name ?? 'Select workspace'}</strong></span>
              <ChevronDown />
            </button>
            {workspaceOpen ? <div className="workspace-switcher__popover">
              <div className="workspace-switcher__heading"><span><small>Account</small><strong>{activeWorkspace?.tenantName ?? session?.user.name}</strong></span><button type="button" onClick={() => setWorkspaceOpen(false)} aria-label="Close workspace menu"><X /></button></div>
              {!creatingWorkspace ? <>
                <div className="workspace-switcher__list" role="menu">
                  {workspaces.map((workspace) => <button key={workspace.id} type="button" role="menuitemradio" aria-checked={workspace.id === activeWorkspace?.id} onClick={() => { selectWorkspace(workspace.id); setWorkspaceOpen(false); }}>
                    <span className="workspace-switcher__initial">{workspace.name.charAt(0).toUpperCase()}</span>
                    <span><strong>{workspace.name}</strong><small>{workspace.role?.replace('_', ' ') ?? 'workspace'}</small></span>
                    {workspace.id === activeWorkspace?.id ? <Check /> : null}
                  </button>)}
                </div>
                <div className="workspace-switcher__actions">{session?.user.role === 'owner' || session?.user.role === 'admin' ? <button type="button" onClick={() => setCreatingWorkspace(true)}><Plus />Create workspace</button> : null}<Link to="/workspace" onClick={() => setWorkspaceOpen(false)}><Settings2 />Manage workspaces</Link></div>
              </> : <form className="workspace-switcher__form" onSubmit={(event) => void submitWorkspace(event)}>
                <strong>Create workspace</strong>
                <label>Name<input autoFocus value={workspaceName} onChange={(event) => { const name = event.target.value; setWorkspaceName(name); setWorkspaceSlug(name.toLowerCase().trim().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')); }} placeholder="CPA Division" /></label>
                <label>Slug<input value={workspaceSlug} onChange={(event) => setWorkspaceSlug(event.target.value)} placeholder="cpa-division" /></label>
                <div><button type="button" onClick={() => setCreatingWorkspace(false)}>Cancel</button><button type="submit" disabled={workspaceName.trim().length < 2 || workspaceSlug.trim().length < 2}>Create</button></div>
              </form>}
            </div> : null}
          </div>
          <div className="topbar__page"><span className="topbar__eyebrow">{activeWorkspace?.name ?? 'Workspace'}</span><h1>{pageTitle(location.pathname)}</h1></div>
        </div>
        <div className="topbar__actions">
          <button className="search-trigger" type="button" aria-label="Search" aria-haspopup="dialog" onClick={() => setCommandOpen(true)}><Search /><span>Search</span><kbd>⌘ K</kbd></button>
          <NotificationBell />
          <div className="account-menu">
            <button className="account-button" onClick={() => setAccountOpen((value) => !value)} aria-expanded={accountOpen}><span className="avatar">{initials}</span><span className="account-copy"><strong>{session?.user.name}</strong><small>{session?.user.role}</small></span><ChevronDown /></button>
            {accountOpen ? <div className="account-popover"><div><strong>{session?.user.name}</strong><small>{session?.user.email}</small></div>{platformAdmin ? <Link to="/platform-admin" onClick={() => setAccountOpen(false)}><ShieldCheck />Platform control plane</Link> : null}<Link to="/workspace" onClick={() => setAccountOpen(false)}><Settings2 />Workspace settings</Link><Link to="/help" onClick={() => setAccountOpen(false)}><CircleHelp />Help Center</Link><button onClick={() => void logout().then(() => navigate('/login'))}><LogOut />Sign out</button></div> : null}
          </div>
        </div>
      </header>
      <main className="content"><Outlet key={activeWorkspace?.id ?? 'workspace-loading'} /></main>
    </div>
    <nav className="mobile-nav" aria-label="Mobile navigation">
      {mobileNavigation.map(({ to, label, icon: Icon, end }) => <NavLink key={to} to={to} end={end} aria-label={label}><Icon /><span>{label}</span></NavLink>)}
    </nav>
    <button className="command-fab" type="button" aria-label="Open command palette" aria-haspopup="dialog" onClick={() => setCommandOpen(true)}><Command /></button>
    <CommandPalette
      open={commandOpen}
      onClose={() => setCommandOpen(false)}
      navigation={visibleNavigation}
      workspaces={workspaces}
      activeWorkspaceId={activeWorkspace?.id}
      onSelectWorkspace={selectWorkspace}
      canViewPlatformAdmin={platformAdmin}
    />
  </div>;
}
