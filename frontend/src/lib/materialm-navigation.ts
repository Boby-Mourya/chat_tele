/** Navigation only. The API remains the authority for resource access. */
export interface NavigationItem {
  to: string;
  label: string;
  icon: 'overview' | 'agents' | 'inbox' | 'leads' | 'integrations' | 'education' | 'analytics' | 'audit' | 'deploy' | 'students' | 'courses' | 'batches' | 'enrollments' | 'imports' | 'access' | 'activity';
  section: 'Workspace' | 'Engagement' | 'Learning' | 'Operations';
  permission: string;
  description?: string;
  end?: boolean;
}

export interface NavigationScope {
  role?: string;
  permissions?: readonly string[];
}

export const primaryNavigation: NavigationItem[] = [
  { to: '/', label: 'Overview', icon: 'overview', section: 'Workspace', permission: 'workspace.view', end: true },
  { to: '/agents', label: 'Agents', icon: 'agents', section: 'Workspace', permission: 'agents.view' },
  { to: '/conversations', label: 'Conversations', icon: 'inbox', section: 'Engagement', permission: 'conversations.view' },
  { to: '/workflows', label: 'Bot Workflows', icon: 'integrations', section: 'Engagement', permission: 'agents.view' },
  { to: '/leads', label: 'Leads', icon: 'leads', section: 'Engagement', permission: 'leads.view' },
  { to: '/crm-workflow', label: 'CRM Workflow', icon: 'integrations', section: 'Engagement', permission: 'crm.view' },
  { to: '/integrations', label: 'Integrations', icon: 'integrations', section: 'Engagement', permission: 'integrations.view' },
  { to: '/education', label: 'Education', icon: 'education', section: 'Learning', permission: 'education.view' },
  { to: '/analytics', label: 'Analytics', icon: 'analytics', section: 'Operations', permission: 'analytics.view' },
  { to: '/audit', label: 'Audit', icon: 'audit', section: 'Operations', permission: 'audit.view' },
  { to: '/deploy', label: 'Deploy', icon: 'deploy', section: 'Operations', permission: 'agents.deploy' },
];

export const educationNavigation: NavigationItem[] = [
  { to: '/education', label: 'Overview', icon: 'education', section: 'Learning', permission: 'education.view', end: true },
  { to: '/education/students', label: 'Students', icon: 'students', section: 'Learning', permission: 'education.view', description: 'Student profiles, identities, enrollments and learning history.' },
  { to: '/education/courses', label: 'Courses', icon: 'courses', section: 'Learning', permission: 'education.view', description: 'Organize the courses available in this workspace.' },
  { to: '/education/batches', label: 'Batches', icon: 'batches', section: 'Learning', permission: 'education.view', description: 'Manage course cohorts and their validity dates.' },
  { to: '/education/enrollments', label: 'Enrollments', icon: 'enrollments', section: 'Learning', permission: 'education.view', description: 'Review student access, assigned agents and enrollment status.' },
  { to: '/education/students/import', label: 'Imports', icon: 'imports', section: 'Learning', permission: 'education.manage', description: 'Use the existing student import, preview and validation workflow.' },
  { to: '/education/access-requests', label: 'Access requests', icon: 'access', section: 'Learning', permission: 'education.view', description: 'Review academy access requests and identity recovery.' },
  { to: '/education/activity', label: 'Activity', icon: 'activity', section: 'Learning', permission: 'education.view', description: 'Browse student activity and links to education conversations.' },
];

export function hasNavigationPermission(scope: NavigationScope, permission: string): boolean {
  if (scope.role === 'owner' || scope.role === 'admin') return true;
  if (permission === 'audit.view' && scope.role === 'security_admin') return true;
  // Older workspace responses omit permissions. Preserve existing navigation
  // compatibility; never use this fallback to authorize an API operation.
  if (!scope.permissions) return permission !== 'audit.view';
  return scope.permissions.includes('*') || scope.permissions.includes(permission);
}

export function visibleNavigation(items: readonly NavigationItem[], scope: NavigationScope): NavigationItem[] {
  return items.filter((item) => hasNavigationPermission(scope, item.permission));
}

export function normalizedPath(pathname: string): string {
  return pathname.split(/[?#]/, 1)[0]?.replace(/\/+$/, '') || '/';
}

export function matchesNavigation(pathname: string, item: Pick<NavigationItem, 'to' | 'end'>): boolean {
  const path = normalizedPath(pathname);
  return path === item.to || (!item.end && item.to !== '/' && path.startsWith(`${item.to}/`));
}

export function educationPage(pathname: string): NavigationItem | undefined {
  return [...educationNavigation].sort((a, b) => b.to.length - a.to.length)
    .find((item) => matchesNavigation(pathname, item));
}

export function materialmPageTitle(pathname: string): string {
  const path = normalizedPath(pathname);
  if (path === '/education' || path.startsWith('/education/')) {
    if (/^\/education\/students\/(?!import(?:\/|$))[^/]+/.test(path)) return 'Student detail';
    return educationPage(path)?.label ?? 'Education';
  }
  if (path.startsWith('/platform-admin')) return 'Platform Control Plane';
  if (path.startsWith('/workspace/white-label')) return 'White Label';
  if (path.startsWith('/workspace')) return 'Workspace';
  if (path.startsWith('/help')) return 'Help Center';
  if (path.startsWith('/agents/')) return path === '/agents/new' ? 'Create agent' : 'Agent workspace';
  return primaryNavigation.find((item) => matchesNavigation(path, item))?.label ?? 'Workspace';
}

export function commandNavigation(scope: NavigationScope): Array<{ to: string; label: string; keywords?: string[] }> {
  return [
    ...visibleNavigation(primaryNavigation, scope).map(({ to, label }) => ({ to, label })),
    ...visibleNavigation(educationNavigation, scope).filter((item) => item.to !== '/education')
      .map(({ to, label }) => ({ to, label: `Education / ${label}`, keywords: ['education', 'academy', label.toLowerCase()] })),
  ];
}
