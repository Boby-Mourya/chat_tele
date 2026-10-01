import { describe, expect, it } from 'vitest';
import { commandNavigation, educationNavigation, educationPage, hasNavigationPermission, materialmPageTitle, matchesNavigation, primaryNavigation, visibleNavigation } from './materialm-navigation';

describe('MaterialM navigation', () => {
  it('groups education under exactly one primary entry', () => {
    expect(primaryNavigation.filter((item) => item.to.startsWith('/education')).map((item) => item.to)).toEqual(['/education']);
  });
  it('keeps every existing education destination', () => {
    expect(educationNavigation.map((item) => item.to)).toEqual([
      '/education', '/education/students', '/education/courses', '/education/batches',
      '/education/enrollments', '/education/students/import', '/education/access-requests', '/education/activity',
    ]);
  });
  it.each([
    ['/education', 'Overview'], ['/education/', 'Overview'],
    ['/education/students/student-1', 'Students'], ['/education/students/import', 'Imports'],
    ['/education/students/import?source=lms', 'Imports'], ['/education/courses/', 'Courses'],
    ['/education/batches#active', 'Batches'], ['/education/enrollments', 'Enrollments'],
  ])('resolves %s to %s', (path, title) => expect(educationPage(path)?.label).toBe(title));
  it('does not use prefix-only matching for unrelated routes', () => {
    expect(matchesNavigation('/education-access-recovery', { to: '/education' })).toBe(false);
    expect(matchesNavigation('/leads-other', { to: '/leads' })).toBe(false);
    expect(educationPage('/education/students-other')).toBeUndefined();
  });
  it('keeps the import route distinct from student detail', () => {
    expect(materialmPageTitle('/education/students/import')).toBe('Imports');
    expect(materialmPageTitle('/education/students/123')).toBe('Student detail');
  });
  it('preserves commercial destinations outside education', () => {
    expect(primaryNavigation.some((item) => item.to === '/leads')).toBe(true);
    expect(primaryNavigation.some((item) => item.to === '/integrations')).toBe(true);
    expect(educationNavigation.every((item) => item.to.startsWith('/education'))).toBe(true);
  });
  it('uses reported workspace permissions to filter navigation', () => {
    const result = visibleNavigation(primaryNavigation, { role: 'member', permissions: ['workspace.view', 'education.view'] });
    expect(result.map((item) => item.to)).toEqual(['/', '/education']);
    expect(visibleNavigation(primaryNavigation, { role: 'member', permissions: [] })).toEqual([]);
  });
  it('preserves owner/admin and security administrator access semantics', () => {
    expect(hasNavigationPermission({ role: 'owner', permissions: [] }, 'education.view')).toBe(true);
    expect(hasNavigationPermission({ role: 'admin' }, 'audit.view')).toBe(true);
    expect(hasNavigationPermission({ role: 'security_admin' }, 'audit.view')).toBe(true);
    expect(hasNavigationPermission({ role: 'member', permissions: ['*'] }, 'education.view')).toBe(true);
    expect(hasNavigationPermission({ role: 'member' }, 'audit.view')).toBe(false);
  });
  it('keeps education pages searchable without duplicating the hub', () => {
    const result = commandNavigation({ role: 'owner' });
    expect(new Set(result.map((item) => item.to)).size).toBe(result.length);
    expect(result.find((item) => item.to === '/education/students/import')?.label).toBe('Education / Imports');
  });
  it('does not expose import commands without education.manage', () => {
    const result = commandNavigation({ role: 'member', permissions: ['education.view'] });
    expect(result.some((item) => item.to === '/education/students')).toBe(true);
    expect(result.some((item) => item.to === '/education/students/import')).toBe(false);
  });
});
