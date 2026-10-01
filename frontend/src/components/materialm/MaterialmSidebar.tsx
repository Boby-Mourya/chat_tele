import { CircleHelp, Settings2 } from 'lucide-react';
import { NavLink } from 'react-router-dom';
import type { NavigationItem } from '@/lib/materialm-navigation';
import { navigationIcons } from './navigation-icons';

interface Props { items: NavigationItem[]; onNavigate?: () => void; }
const sections: NavigationItem['section'][] = ['Workspace', 'Engagement', 'Learning', 'Operations'];

/** Adapts MaterialM Sidebaritems + NavItems to Northstar's existing routes. */
export function MaterialmSidebarLinks({ items, onNavigate }: Props) {
  return <>
    <nav className="mm-sidebar__navigation" aria-label="Application pages">
      {sections.map((section) => {
        const links = items.filter((item) => item.section === section);
        if (!links.length) return null;
        return <div className="mm-sidebar__group" key={section}>
          <p className="mm-sidebar__heading">{section}</p>
          {links.map((item) => {
            const Icon = navigationIcons[item.icon];
            return <NavLink key={item.to} to={item.to} end={item.end} aria-label={item.label} title={item.label} onClick={onNavigate} className={({ isActive }) => `mm-nav-link${isActive ? ' is-active' : ''}`}>
              <Icon aria-hidden="true" /><span>{item.label}</span>
            </NavLink>;
          })}
        </div>;
      })}
    </nav>
    <div className="mm-sidebar__footer">
      <NavLink to="/workspace" aria-label="Workspace settings" title="Workspace settings" onClick={onNavigate} className={({ isActive }) => `mm-nav-link${isActive ? ' is-active' : ''}`}><Settings2 aria-hidden="true" /><span>Workspace settings</span></NavLink>
      <NavLink to="/help" aria-label="Help Center" title="Help Center" onClick={onNavigate} className={({ isActive }) => `mm-nav-link${isActive ? ' is-active' : ''}`}><CircleHelp aria-hidden="true" /><span>Help Center</span></NavLink>
    </div>
  </>;
}
