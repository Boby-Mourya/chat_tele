import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { HelpCenterPage } from '@/pages/HelpCenterPage';
import { demoHelpHome } from '@/lib/help-demo-data';

const apiMocks = vi.hoisted(() => ({ home: vi.fn(), article: vi.fn() }));
vi.mock('@/lib/api', () => ({ api: { help: apiMocks } }));

describe('HelpCenterPage', () => {
  afterEach(() => { cleanup(); vi.clearAllMocks(); localStorage.clear(); });
  it('renders search, role-aware categories, and support inside the Help page', async () => {
    apiMocks.home.mockResolvedValue(demoHelpHome());
    apiMocks.article.mockRejectedValue(new Error('not recent'));
    render(<MemoryRouter><HelpCenterPage /></MemoryRouter>);
    expect(await screen.findByRole('heading', { name: 'How can we help?' })).toBeInTheDocument();
    expect(screen.getByRole('searchbox', { name: 'Search Northstar Help' })).toBeInTheDocument();
    expect(screen.getByText('Browse by category')).toBeInTheDocument();
    expect(screen.getByText('Still need help?')).toBeInTheDocument();
  });
});
