// @vitest-environment jsdom
import { act, cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { useWorkspace } from '@/components/providers';
import { workspaceSettingsApi, type ExtendedBranding } from '@/features/workspace/settings/workspaceSettings.api';
import { applyBrandTokens } from '@/theme/brand-tokens';
import { WorkspaceBrandRuntime, useWorkspaceBrandRuntime } from './WorkspaceBrandRuntime';

vi.mock('@/components/providers', () => ({ useWorkspace: vi.fn() }));
vi.mock('@/features/workspace/settings/workspaceSettings.api', () => ({
  workspaceSettingsApi: { runtimeBranding: vi.fn() },
}));
vi.mock('@/theme/brand-tokens', () => ({ applyBrandTokens: vi.fn(() => vi.fn()) }));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((complete) => { resolve = complete; });
  return { promise, resolve };
}

function brand(companyName: string): ExtendedBranding {
  return {
    identity: {
      companyName,
      brandedDashboard: true,
      browserTitle: `${companyName} Portal`,
      primaryColor: '#112233',
      secondaryColor: '#445566',
    },
    colors: {},
    typography: {},
    appearance: { borderRadius: 12 },
  } as unknown as ExtendedBranding;
}

function CurrentBrand() {
  const value = useWorkspaceBrandRuntime();
  return <span data-testid="current-brand">{value?.identity.companyName ?? 'none'}</span>;
}

describe('WorkspaceBrandRuntime workspace isolation', () => {
  it('clears the previous brand immediately and ignores a late response after switching workspaces', async () => {
    let activeWorkspaceId = 'workspace-a';
    vi.mocked(useWorkspace).mockImplementation(() => ({
      activeWorkspace: { id: activeWorkspaceId },
    } as unknown as ReturnType<typeof useWorkspace>));
    const first = deferred<ExtendedBranding | null>();
    const second = deferred<ExtendedBranding | null>();
    vi.mocked(workspaceSettingsApi.runtimeBranding)
      .mockImplementationOnce(() => first.promise)
      .mockImplementationOnce(() => second.promise);
    document.title = 'Platform Portal';

    const view = render(<WorkspaceBrandRuntime><CurrentBrand /></WorkspaceBrandRuntime>);
    expect(screen.getByTestId('current-brand').textContent).toBe('none');
    await act(async () => { first.resolve(brand('Workspace A')); });
    expect(screen.getByTestId('current-brand').textContent).toBe('Workspace A');
    expect(document.title).toBe('Workspace A Portal');

    activeWorkspaceId = 'workspace-b';
    view.rerender(<WorkspaceBrandRuntime><CurrentBrand /></WorkspaceBrandRuntime>);
    expect(screen.getByTestId('current-brand').textContent).toBe('none');
    expect(document.title).toBe('Platform Portal');

    await act(async () => { second.resolve(brand('Workspace B')); });
    expect(screen.getByTestId('current-brand').textContent).toBe('Workspace B');
    expect(document.title).toBe('Workspace B Portal');
    expect(vi.mocked(applyBrandTokens)).toHaveBeenCalledTimes(2);
  });

  it('does not display the result of an obsolete in-flight branding request', async () => {
    let activeWorkspaceId = 'workspace-a';
    vi.mocked(useWorkspace).mockImplementation(() => ({
      activeWorkspace: { id: activeWorkspaceId },
    } as unknown as ReturnType<typeof useWorkspace>));
    const first = deferred<ExtendedBranding | null>();
    const second = deferred<ExtendedBranding | null>();
    vi.mocked(workspaceSettingsApi.runtimeBranding)
      .mockImplementationOnce(() => first.promise)
      .mockImplementationOnce(() => second.promise);

    const view = render(<WorkspaceBrandRuntime><CurrentBrand /></WorkspaceBrandRuntime>);
    activeWorkspaceId = 'workspace-b';
    view.rerender(<WorkspaceBrandRuntime><CurrentBrand /></WorkspaceBrandRuntime>);
    await act(async () => { first.resolve(brand('Workspace A')); });
    expect(screen.getByTestId('current-brand').textContent).toBe('none');
    await act(async () => { second.resolve(brand('Workspace B')); });
    expect(screen.getByTestId('current-brand').textContent).toBe('Workspace B');
  });
});
