// @vitest-environment jsdom
import { useState, type ReactNode } from 'react';
import { act, cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { useAuth, useWorkspace } from '@/components/providers';
import type { ExtendedBranding, DashboardWidget } from '@/features/workspace/settings/workspaceSettings.api';
import { loadWorkspaceDashboardRuntime } from './dashboard.api';
import type { DashboardData, WorkspaceDashboardRuntime } from './dashboard.types';
import { DashboardPage } from './DashboardPage';

let currentWorkspaceId = 'workspace-a';
let hookInvocation = 0;

vi.mock('@/components/providers', () => ({ useAuth: vi.fn(), useWorkspace: vi.fn() }));
vi.mock('@/lib/use-api', () => ({
  useApi: () => {
    // Emulate useApi retaining its initial data during a rerender. A keyed
    // dashboard remount must initialize fresh API state for the new workspace.
    const kind = hookInvocation++ % 4;
    const [data] = useState(() => kind === 0
      ? [{ name: `Agent ${currentWorkspaceId}`, status: 'active' }]
      : kind === 1 || kind === 2 ? { items: [] } : null);
    return { data, loading: false, error: null, reload: vi.fn() };
  },
}));
vi.mock('./dashboard.api', () => ({ loadWorkspaceDashboardRuntime: vi.fn() }));
vi.mock('./DashboardGrid', () => ({
  DashboardGrid: ({ widgets, renderWidget }: { widgets: DashboardWidget[]; renderWidget: (widget: DashboardWidget) => ReactNode }) =>
    <div data-testid="dashboard-grid">{widgets.map((widget) => <div key={widget.id}>{renderWidget(widget)}</div>)}</div>,
}));
vi.mock('./widgets/DashboardWidgetRenderer', () => ({
  DashboardWidgetRenderer: ({ data }: { data: DashboardData }) =>
    <span data-testid="agent-name">{data.agents[0]?.name ?? 'no agent'}</span>,
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  currentWorkspaceId = 'workspace-a';
  hookInvocation = 0;
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((complete) => { resolve = complete; });
  return { promise, resolve };
}

function runtime(version: number): WorkspaceDashboardRuntime {
  return {
    dashboard: {
      layoutVersion: version,
      landingScreen: 'overview',
      widgets: [{ id: `agent-${version}`, type: 'agent-activity', x: 0, y: 0, width: 4, height: 2, visible: true, audience: [], config: {} }],
    },
    appearance: {} as WorkspaceDashboardRuntime['appearance'],
    industry: 'education',
    country: 'IN',
    enabledFeatures: [],
  };
}

const brand = {
  identity: { companyName: 'Workspace Portal' },
  dashboard: runtime(1).dashboard,
} as unknown as ExtendedBranding;

function mockCurrentWorkspace() {
  vi.mocked(useWorkspace).mockImplementation(() => ({
    activeWorkspace: { id: currentWorkspaceId, role: 'manager', permissions: ['agents.view'] },
  } as unknown as ReturnType<typeof useWorkspace>));
  vi.mocked(useAuth).mockReturnValue({
    session: { user: { name: 'Workspace Tester' } },
  } as unknown as ReturnType<typeof useAuth>);
}

describe('DashboardPage workspace isolation', () => {
  it('clears the previous workspace runtime and API data immediately on switch', async () => {
    mockCurrentWorkspace();
    const first = deferred<WorkspaceDashboardRuntime>();
    const second = deferred<WorkspaceDashboardRuntime>();
    vi.mocked(loadWorkspaceDashboardRuntime)
      .mockImplementationOnce(() => first.promise)
      .mockImplementationOnce(() => second.promise);

    const view = render(<DashboardPage brand={brand} />);
    await act(async () => { first.resolve(runtime(7)); });
    expect(screen.getByText('Layout v7')).toBeTruthy();
    expect(screen.getByTestId('agent-name').textContent).toBe('Agent workspace-a');

    currentWorkspaceId = 'workspace-b';
    view.rerender(<DashboardPage brand={brand} />);
    expect(screen.getByText('Layout v1')).toBeTruthy();
    expect(screen.getByTestId('agent-name').textContent).toBe('Agent workspace-b');

    await act(async () => { second.resolve(runtime(8)); });
    expect(screen.getByText('Layout v8')).toBeTruthy();
    expect(screen.getByTestId('agent-name').textContent).toBe('Agent workspace-b');
  });

  it('ignores an obsolete runtime response after switching workspaces', async () => {
    mockCurrentWorkspace();
    const first = deferred<WorkspaceDashboardRuntime>();
    const second = deferred<WorkspaceDashboardRuntime>();
    vi.mocked(loadWorkspaceDashboardRuntime)
      .mockImplementationOnce(() => first.promise)
      .mockImplementationOnce(() => second.promise);

    const view = render(<DashboardPage brand={brand} />);
    currentWorkspaceId = 'workspace-b';
    view.rerender(<DashboardPage brand={brand} />);
    await act(async () => { first.resolve(runtime(7)); });
    expect(screen.queryByText('Layout v7')).toBeNull();
    expect(screen.getByTestId('agent-name').textContent).toBe('Agent workspace-b');

    await act(async () => { second.resolve(runtime(8)); });
    expect(screen.getByText('Layout v8')).toBeTruthy();
  });
});
