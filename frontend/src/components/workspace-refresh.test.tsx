import { useEffect, useState } from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Session } from '@/types';
import { AuthProvider, WorkspaceProvider, useWorkspace } from '@/components/providers';
import { WorkspaceSetupGate } from '@/components/WorkspaceSetup';
import { setupApi, SetupRequestError, type SetupBootstrap } from '@/lib/setup-api';
import { persistActiveWorkspace, workspaceApi, workspaceDefaults, WorkspaceRequestError } from '@/lib/workspace-api';

const holder = vi.hoisted(() => ({ session: null as Session | null, mounts: 0 }));
vi.mock('@/lib/api', () => ({ AUTH_SESSION_EVENT: 'northstar:session-changed', api: { auth: { session: () => holder.session } } }));
vi.mock('@/lib/mfa-api', () => ({ isMFAChallenge: () => false, mfaApi: {} }));
vi.mock('@/lib/signup-api', () => ({ signupApi: {} }));
vi.mock('@/lib/setup-api', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/lib/setup-api')>();
  return { ...original, setupApi: { ...original.setupApi, bootstrap: vi.fn() } };
});
const workspace = { ...workspaceDefaults, id: 'workspace-1', tenantId: 'tenant-1', permissions: ['workspace.view'] };
const bootstrap: SetupBootstrap = {
  organization: { id: 'tenant-1', name: 'Academy', role: 'owner' }, workspaceId: 'workspace-1',
  capabilities: { organization: [], workspace: ['workspace.view'] },
  onboarding: { revision: 1, profileComplete: true, profileRequired: true, brandingChoice: 'keep_default', choiceAt: null, catalogGrants: [], onboardingVersion: 1 },
  starterContent: [], brand: {}, usage: null,
  plan: { name: 'free', status: 'active', workspaceLimit: 1, agentLimit: 1, memberLimit: 1, monthlyConversationLimit: 100, monthlyTokenLimit: 1000, storageLimitBytes: 1000, dashboardCustomize: true, customDomain: false, brandedEmail: false, removePlatformMark: false },
};

function writeSession(serial = 1, cv = 0, role: Session['user']['role'] = 'owner') {
  holder.session = {
    accessToken: `test.${btoa(JSON.stringify({ tid: 'tenant-1', cv, role, jti: serial }))}.fixture`,
    expiresAt: '2099-01-01T00:00:00Z', user: { id: 'owner-1', name: 'Owner', email: 'owner@example.com', role, emailVerified: true },
  };
  localStorage.setItem('northstar.session', JSON.stringify(holder.session));
}
function DraftProbe() {
  const { refreshWorkspaces } = useWorkspace();
  const [value, setValue] = useState('');
  useEffect(() => { holder.mounts += 1; }, []);
  return <><input aria-label="Unsaved draft" value={value} onChange={(event) => setValue(event.target.value)} /><button onClick={() => void refreshWorkspaces().catch(() => undefined)}>Refresh capabilities</button></>;
}
function mount() {
  render(<MemoryRouter><AuthProvider><WorkspaceProvider><WorkspaceSetupGate><DraftProbe /></WorkspaceSetupGate></WorkspaceProvider></AuthProvider></MemoryRouter>);
}

beforeEach(() => {
  holder.mounts = 0; writeSession(); persistActiveWorkspace('workspace-1');
  vi.spyOn(workspaceApi, 'list').mockResolvedValue([workspace]);
  vi.mocked(setupApi.bootstrap).mockReset().mockResolvedValue(bootstrap);
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); localStorage.clear(); sessionStorage.clear(); });

describe('workspace refresh preserves local editor state', () => {
  it('does not remount an editor when only the access token rotates', async () => {
    mount(); const input = await screen.findByRole('textbox', { name: 'Unsaved draft' });
    fireEvent.change(input, { target: { value: 'Keep my unfinished branding' } });
    await act(async () => { writeSession(2); window.dispatchEvent(new Event('northstar:session-changed')); });
    await waitFor(() => expect(setupApi.bootstrap).toHaveBeenCalledTimes(2));
    expect(screen.getByRole('textbox')).toHaveValue('Keep my unfinished branding');
    expect(holder.mounts).toBe(1);
    expect(workspaceApi.list).toHaveBeenCalledTimes(1);
  });

  it('retains an editor while a manual capability refresh is pending', async () => {
    mount(); const input = await screen.findByRole('textbox'); fireEvent.change(input, { target: { value: 'Draft' } });
    let finish: (value: typeof workspace[]) => void = () => undefined;
    vi.mocked(workspaceApi.list).mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
    fireEvent.click(screen.getByRole('button', { name: 'Refresh capabilities' }));
    expect(screen.getByRole('textbox')).toHaveValue('Draft');
    await act(async () => finish([workspace]));
    expect(holder.mounts).toBe(1);
  });

  it('retains a known view during a transient workspace-list outage', async () => {
    mount(); const input = await screen.findByRole('textbox'); fireEvent.change(input, { target: { value: 'Draft' } });
    vi.mocked(workspaceApi.list).mockRejectedValueOnce(new WorkspaceRequestError('Temporary outage', 503));
    fireEvent.click(screen.getByRole('button', { name: 'Refresh capabilities' }));
    await screen.findByText(/Workspace information could not refresh/);
    expect(screen.getByRole('textbox')).toHaveValue('Draft');
    expect(holder.mounts).toBe(1);
  });

  it('retains an editor during a transient bootstrap outage after rotation', async () => {
    mount(); const input = await screen.findByRole('textbox'); fireEvent.change(input, { target: { value: 'Draft' } });
    vi.mocked(setupApi.bootstrap).mockRejectedValueOnce(new SetupRequestError('Temporary bootstrap outage', 503));
    await act(async () => { writeSession(2); window.dispatchEvent(new Event('northstar:session-changed')); });
    await screen.findByText(/Workspace information could not refresh/);
    expect(screen.getByRole('textbox')).toHaveValue('Draft');
  });

  it('clears private child state when access is denied', async () => {
    mount(); await screen.findByRole('textbox');
    vi.mocked(workspaceApi.list).mockRejectedValueOnce(new WorkspaceRequestError('Membership removed', 403));
    fireEvent.click(screen.getByRole('button', { name: 'Refresh capabilities' }));
    await screen.findByText('Membership removed');
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
  });

  it('treats a credential-version change as a new context, not ordinary refresh', async () => {
    mount(); const input = await screen.findByRole('textbox'); fireEvent.change(input, { target: { value: 'Old credentials draft' } });
    await act(async () => { writeSession(2, 1); window.dispatchEvent(new Event('northstar:session-changed')); });
    await waitFor(() => expect(holder.mounts).toBe(2));
    expect(screen.getByRole('textbox')).toHaveValue('');
  });
});
