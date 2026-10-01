import { Link, Outlet, useLocation } from 'react-router-dom';
import { BookOpen, ChevronRight, GraduationCap } from 'lucide-react';
import { useAuth, useWorkspace } from '@/components/providers';
import { educationNavigation, educationPage, hasNavigationPermission, visibleNavigation } from '@/lib/materialm-navigation';
import { navigationIcons } from './navigation-icons';

export function EducationLayout() {
  const { activeWorkspace, loading } = useWorkspace();
  const { session } = useAuth();
  const { pathname } = useLocation();
  const scope = { role: session?.user.role, permissions: activeWorkspace?.permissions };
  const knowledgePage = pathname.startsWith('/education/knowledge');
  const selected = knowledgePage ? { to: '/education/knowledge', label: 'Course knowledge', permission: 'knowledge.view' } : educationPage(pathname);
  if (loading && !activeWorkspace) return <div className="mm-empty" role="status">Loading education workspace…</div>;
  if (!activeWorkspace) return <div className="mm-empty">Select an authorized workspace to open Education.</div>;
  if (!hasNavigationPermission(scope, 'education.view') || (selected && !hasNavigationPermission(scope, selected.permission))) {
    return <section className="mm-empty" aria-label="Education access unavailable"><h2>Education access unavailable</h2><p>Your workspace role does not include access to this Education section.</p></section>;
  }
  return <div className="mm-education" data-business-domain="education">
    <div className="mm-education__bar">
      <nav aria-label="Education breadcrumb" className="mm-breadcrumb">
        <Link to="/education"><GraduationCap aria-hidden="true" />Education</Link>
        {selected && selected.to !== '/education' ? <><ChevronRight aria-hidden="true" /><span>{selected.label}</span></> : null}
      </nav>
      <span className="mm-domain-label">Learning workspace</span>
    </div>
    <nav className="mm-education__nav" aria-label="Education navigation">
      {visibleNavigation(educationNavigation, scope).map((item) => {
        const Icon = navigationIcons[item.icon];
        const active = selected?.to === item.to;
        return <Link key={item.to} to={item.to} aria-current={active ? 'page' : undefined} className={active ? 'is-active' : undefined}>
          <Icon aria-hidden="true" /><span>{item.label}</span>
        </Link>;
      })}
      {hasNavigationPermission(scope, 'knowledge.view') && <Link to="/education/knowledge" aria-current={knowledgePage ? 'page' : undefined} className={knowledgePage ? 'is-active' : undefined}><BookOpen aria-hidden="true" /><span>Course knowledge</span></Link>}
    </nav>
    <div className="mm-education__content"><Outlet /></div>
  </div>;
}
