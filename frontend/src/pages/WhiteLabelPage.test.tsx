import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { WorkspaceNavigation } from '@/components/workspace-navigation';
import { ToastProvider } from '@/components/providers';
import { WhiteLabelPage } from '@/pages/WhiteLabelPage';
import type { WorkspaceSettings } from '@/lib/workspace-api';

const workspace: WorkspaceSettings = {
  id: 'workspace-test', name: 'Test Workspace', slug: 'test', plan: 'business', memberCount: 1,
  preferences: { timezone: 'UTC', defaultLanguage: 'English', dateFormat: 'YYYY-MM-DD' },
  security: { sensitiveDataMasking: true, securityContact: null },
  whiteLabel: {
    companyName: 'Northstar AI', logoDataUrl: '', faviconDataUrl: '', appIconDataUrl: '',
    primaryColor: '#146cf6', secondaryColor: '#705cf6', supportEmail: 'support@example.com',
    supportUrl: 'https://example.com/help', browserTitle: 'Northstar AI', customDomain: '',
    dnsStatus: 'not-configured', brandedLogin: true, brandedDashboard: true, brandedWidget: true,
    brandedEmails: true, removePlatformBranding: false,
  },
};

const apiMocks = vi.hoisted(() => ({ get: vi.fn(), update: vi.fn() }));
vi.mock('@/lib/workspace-api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/workspace-api')>()),
  workspaceApi: apiMocks,
}));

describe('White Label workspace', () => {
  beforeEach(() => {
    apiMocks.get.mockResolvedValue(structuredClone(workspace));
    apiMocks.update.mockImplementation(async (patch) => ({ ...structuredClone(workspace), ...patch }));
  });
  afterEach(() => { cleanup(); vi.clearAllMocks(); });

  it('opens White Label in a new internal tab', () => {
    render(<WorkspaceNavigation active="workspace" onSelect={() => undefined} />);
    const link = screen.getByRole('link', { name: /White Label/ });
    expect(link).toHaveAttribute('href', '/workspace/white-label');
    expect(link).toHaveAttribute('target', '_blank');
  });

  it('updates the branded preview immediately and saves the configuration', async () => {
    const user = userEvent.setup();
    render(<MemoryRouter><ToastProvider><WhiteLabelPage /></ToastProvider></MemoryRouter>);
    const name = await screen.findByLabelText('Company or product name');
    await user.clear(name);
    await user.type(name, 'Acme Assist');
    expect(screen.getAllByText('Acme Assist').length).toBeGreaterThan(0);
    await user.click(screen.getAllByRole('button', { name: 'Save changes' })[0]!);
    expect(apiMocks.update).toHaveBeenCalledWith(expect.objectContaining({
      whiteLabel: expect.objectContaining({ companyName: 'Acme Assist' }),
    }));
  });
});
