import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { EducationHubPage } from './EducationHubPage';
import { OverviewPage } from './OverviewPage';
import { demoAgents, demoAnalytics } from '@/lib/demo-data';

const mocks = vi.hoisted(() => ({ courses: vi.fn(), enrollments: vi.fn(), agents: vi.fn(), analytics: vi.fn(), conversations: vi.fn() }));
vi.mock('@/components/providers', () => ({ useAuth: () => ({ session: { user: { name: 'Sam Owner', role: 'owner' } } }), useWorkspace: () => ({ activeWorkspace: { id: 'academy' } }) }));
vi.mock('@/lib/education-api', () => ({ educationApi: { courses: { list: mocks.courses } } }));
vi.mock('@/lib/education-enrollment-api', () => ({ educationEnrollmentApi: { list: mocks.enrollments } }));
vi.mock('@/lib/api', () => ({ api: { agents: { list: mocks.agents }, analytics: { summary: mocks.analytics }, conversations: { list: mocks.conversations } } }));
afterEach(cleanup);
beforeEach(() => {
  vi.clearAllMocks();
  mocks.courses.mockResolvedValue([
    { id: 'cma', code: 'CMA-P1', name: 'CMA', status: 'active', description: 'Accounting course', createdAt: new Date().toISOString() },
    { id: 'old', code: 'OLD', name: 'Archived course', status: 'archived', description: '', createdAt: '2020-01-01T00:00:00Z' },
  ]);
  mocks.enrollments.mockResolvedValue([{ id: 'enrolled', courseId: 'cma', status: 'active', createdAt: new Date().toISOString() }]);
  mocks.agents.mockResolvedValue([{ ...structuredClone(demoAgents[0]!), id: 'live-agent', name: 'Live agent', status: 'active' }, { ...structuredClone(demoAgents[0]!), id: 'draft-agent', name: 'Draft agent', status: 'draft' }]);
  mocks.analytics.mockResolvedValue({ ...demoAnalytics, conversations: 23, chart: [{ label: 'Mon', conversations: 23, resolved: 12 }] });
  mocks.conversations.mockResolvedValue({ items: [], total: 0 });
});

describe('PDF dashboard interactions', () => {
  it('shows real courses, filters archived records, and changes chart periods', async () => {
    const user = userEvent.setup();
    render(<MemoryRouter><EducationHubPage /></MemoryRouter>);
    expect(await screen.findByRole('link', { name: 'View course CMA' })).toHaveAttribute('href', '/education/courses?search=CMA-P1');
    expect(screen.getByRole('heading', { name: 'Hello Sam!' })).toBeInTheDocument();
    await user.click(within(screen.getByRole('group', { name: 'Filter academy courses' })).getByRole('button', { name: 'Archived' }));
    expect(screen.queryByRole('link', { name: 'View course CMA' })).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'View course Archived course' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Next course' }));
    expect(screen.getByRole('link', { name: 'Continue with Archived course' })).toHaveAttribute('href', '/education/courses?search=OLD');
    await user.selectOptions(screen.getByLabelText('Academy chart period'), '30');
    expect(screen.getByRole('img', { name: 'Enrollments created in the last 30 days' })).toBeInTheDocument();
    expect(mocks.enrollments).toHaveBeenCalledTimes(1);
  });

  it('shows an API failure rather than invented courses and supports retry', async () => {
    mocks.courses.mockRejectedValueOnce(new Error('Catalog offline'));
    render(<MemoryRouter><EducationHubPage /></MemoryRouter>);
    expect(await screen.findByText('Catalog offline')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByRole('link', { name: 'View course CMA' })).toBeInTheDocument();
  });

  it('filters agents, changes the featured agent and fetches monthly statistics', async () => {
    const user = userEvent.setup();
    render(<MemoryRouter><OverviewPage /></MemoryRouter>);
    expect(await screen.findByRole('link', { name: 'Open Live agent' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Next agent' }));
    expect(screen.getByRole('link', { name: 'Continue with Draft agent' })).toHaveAttribute('href', '/agents/draft-agent/instructions');
    await user.click(within(screen.getByRole('group', { name: 'Filter agents' })).getByRole('button', { name: 'Draft' }));
    expect(screen.queryByRole('link', { name: 'Open Live agent' })).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open Draft agent' })).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText('Chart period'), '30');
    expect(mocks.analytics).toHaveBeenLastCalledWith(30);
    await user.click(screen.getByRole('button', { name: 'Resolved' }));
    expect(await screen.findByRole('img', { name: 'Resolved conversations trend' })).toBeInTheDocument();
  });
});
