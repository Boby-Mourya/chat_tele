// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { DomainRecord, WorkspaceSettingsBundle } from '@/features/workspace/settings/workspaceSettings.api';
import { BrandDomainsSettings } from './BrandDomainsSettings';

vi.mock('@/components/providers', () => ({
  useToast: () => ({ pushToast: vi.fn() }),
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function renderWithDomain(status: DomainRecord['status']) {
  const domain = {
    id: 'domain-1',
    hostname: 'portal.example.com',
    verificationName: '_northstar-verify.portal.example.com',
    verificationValue: 'ownership-token',
    createdAt: '2026-09-21T00:00:00Z',
    status,
    failureReason: status === 'failed' ? 'Background worker dispatch is unavailable' : '',
  } as DomainRecord;
  const bundle = { domains: { domains: [domain] } } as WorkspaceSettingsBundle;
  render(<BrandDomainsSettings bundle={bundle} onChange={vi.fn()} />);
  return {
    dns: screen.getByRole('button', { name: 'Check DNS ownership' }) as HTMLButtonElement,
    tls: screen.getByRole('button', { name: 'Check TLS & activate' }) as HTMLButtonElement,
  };
}

describe('Workspace custom-domain activation eligibility', () => {
  it('requires fresh DNS verification after a failed operation', () => {
    const { dns, tls } = renderWithDomain('failed');
    expect(dns.disabled).toBe(false);
    expect(tls.disabled).toBe(true);
    expect(screen.getByText('Verify DNS ownership again before checking TLS.')).toBeTruthy();
  });

  it.each(['verified', 'certificate_pending'] as const)(
    'allows TLS checks for the ownership-verified %s state',
    (status) => {
      const { tls } = renderWithDomain(status);
      expect(tls.disabled).toBe(false);
    },
  );

  it.each(['pending', 'dns_pending', 'verifying', 'active', 'disabled'] as const)(
    'does not offer TLS activation for the %s state',
    (status) => {
      const { tls } = renderWithDomain(status);
      expect(tls.disabled).toBe(true);
    },
  );
});
