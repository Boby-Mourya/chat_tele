// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { EducationLayout } from './EducationLayout';
import { EducationHubPage } from '@/pages/EducationHubPage';
import { MaterialmSidebarLinks } from './MaterialmSidebar';
import { primaryNavigation } from '@/lib/materialm-navigation';

const context = vi.hoisted(() => ({
  role: 'member', permissions: ['education.view', 'education.manage'],
  workspaceId: 'workspace-a', loading: false,
}));
vi.mock('@/lib/education-api', () => ({ educationApi: { courses: { list: async () => [] } } }));
vi.mock('@/lib/education-enrollment-api', () => ({ educationEnrollmentApi: { list: async () => [] } }));
vi.mock('@/components/providers', () => ({
  useAuth: () => ({ session: { user: { role: context.role } } }),
  useWorkspace: () => ({ activeWorkspace: { id: context.workspaceId, name: 'Academy A', permissions: context.permissions }, loading: context.loading }),
}));

function renderEducation(path = '/education') {
  return render(<MemoryRouter initialEntries={[path]}><Routes>
    <Route path="education" element={<EducationLayout />}>
      <Route index element={<EducationHubPage />} />
      <Route path="students" element={<div>Existing student directory</div>} />
      <Route path="students/import" element={<div>Existing import workflow</div>} />
      <Route path="students/:studentId" element={<div>Existing student detail</div>} />
    </Route>
  </Routes></MemoryRouter>);
}

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
beforeEach(() => { context.role = 'member'; context.permissions = ['education.view', 'education.manage']; });

describe('Unified education workspace', () => {
  it('renders the hub without querying CRM or adding demo statistics', () => {
    const fetchMock = vi.fn(); vi.stubGlobal('fetch', fetchMock);
    renderEducation();
    expect(screen.getByRole('heading', { name: 'Hello there!' })).toBeInTheDocument();
    const nav = screen.getByRole('navigation', { name: 'Education navigation' });
    expect(within(nav).getAllByRole('link')).toHaveLength(8);
    expect(fetchMock).not.toHaveBeenCalled();
    expect(within(nav).queryByRole('link', { name: /CRM|Leads|Integrations/ })).not.toBeInTheDocument();
  });
  it('navigates to the existing student page inside the education layout', async () => {
    renderEducation();
    await userEvent.click(within(screen.getByRole('navigation', { name: 'Education navigation' })).getByRole('link', { name: 'Students' }));
    expect(screen.getByText('Existing student directory')).toBeInTheDocument();
    expect(screen.getByRole('navigation', { name: 'Education navigation' })).toBeInTheDocument();
  });
  it('selects Imports, not Students, on the import deep link', () => {
    renderEducation('/education/students/import');
    const nav = screen.getByRole('navigation', { name: 'Education navigation' });
    expect(within(nav).getByRole('link', { name: 'Imports' })).toHaveAttribute('aria-current', 'page');
    expect(within(nav).getByRole('link', { name: 'Students' })).not.toHaveAttribute('aria-current');
  });
  it('retains student-detail deep links and the selected Students section', () => {
    renderEducation('/education/students/student-42');
    expect(screen.getByText('Existing student detail')).toBeInTheDocument();
    const nav = screen.getByRole('navigation', { name: 'Education navigation' });
    expect(within(nav).getByRole('link', { name: 'Students' })).toHaveAttribute('aria-current', 'page');
  });
  it('does not render protected child screens when explicit education access is absent', () => {
    context.permissions = ['workspace.view'];
    renderEducation('/education/students');
    expect(screen.getByRole('heading', { name: 'Education access unavailable' })).toBeInTheDocument();
    expect(screen.queryByText('Existing student directory')).not.toBeInTheDocument();
  });
  it('blocks the direct import route without management permission', () => {
    context.permissions = ['education.view']; renderEducation('/education/students/import');
    expect(screen.queryByText('Existing import workflow')).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Education access unavailable' })).toBeInTheDocument();
  });
  it('hides import navigation without management permission', () => {
    context.permissions = ['education.view']; renderEducation();
    const nav = screen.getByRole('navigation', { name: 'Education navigation' });
    expect(within(nav).queryByRole('link', { name: 'Imports' })).not.toBeInTheDocument();
  });
  it('uses the full same navigation for desktop and the mobile drawer', async () => {
    const onNavigate = vi.fn();
    render(<MemoryRouter><MaterialmSidebarLinks items={primaryNavigation} onNavigate={onNavigate} /></MemoryRouter>);
    const nav = screen.getByRole('navigation', { name: 'Application pages' });
    expect(within(nav).getAllByRole('link')).toHaveLength(primaryNavigation.length);
    expect(within(nav).getAllByRole('link', { name: 'Education' })).toHaveLength(1);
    await userEvent.click(within(nav).getByRole('link', { name: 'Integrations' }));
    expect(onNavigate).toHaveBeenCalledTimes(1);
  });
});
