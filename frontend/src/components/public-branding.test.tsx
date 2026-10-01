import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { PublicBrandingProvider, usePublicBranding } from '@/components/public-branding';

function Probe() {
  const brand = usePublicBranding();
  return <div>{brand?.companyName ?? 'unbranded'}</div>;
}

describe('PublicBrandingProvider', () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    document.title = '';
    const root = document.documentElement;
    ['--brand-primary','--brand-secondary','--brand-accent','--brand-background','--brand-surface','--brand-border','--brand-text','--brand-muted','--brand-sidebar','--brand-sidebar-text','--brand-font'].forEach((name) => root.style.removeProperty(name));
    document.querySelectorAll('link[rel="icon"]').forEach((node) => node.remove());
  });

  it('loads hostname branding before auth and applies safe presentation tokens', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      workspaceId: 'workspace-1',
      companyName: 'Acme Academy',
      browserTitle: 'Acme Portal',
      logoDataUrl: 'data:image/png;base64,AA==',
      faviconDataUrl: 'data:image/png;base64,AA==',
      primaryColor: '#123456',
      secondaryColor: '#654321',
      colors: {
        accent: '#abcdef',
        background: '#ffffff',
        surface: '#f8fafc',
        border: '#e2e8f0',
        textPrimary: '#111111',
        textSecondary: '#666666',
        sidebarBackground: '#222222',
        sidebarText: '#ffffff',
      },
      typography: { bodyFont: 'Inter' },
      authentication: { signupTitle: 'Join Acme', footer: 'Acme footer' },
      supportUrl: 'https://support.example.com',
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }));
    vi.stubGlobal('fetch', fetchMock);

    render(<PublicBrandingProvider><Probe /></PublicBrandingProvider>);

    expect(await screen.findByText('Acme Academy')).toBeInTheDocument();
    await waitFor(() => expect(document.title).toBe('Acme Portal'));
    expect(document.documentElement.style.getPropertyValue('--brand-primary')).toBe('#123456');
    expect(document.documentElement.style.getPropertyValue('--brand-accent')).toBe('#abcdef');
    expect(document.documentElement.style.getPropertyValue('--brand-font')).toBe('Inter');
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/branding/public?hostname='), expect.objectContaining({ credentials: 'omit' }));
  });
});
