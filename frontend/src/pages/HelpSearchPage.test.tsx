import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { HelpSearchPage } from '@/pages/HelpSearchPage';
import { demoHelpSearch } from '@/lib/help-demo-data';

const apiMocks = vi.hoisted(() => ({ search: vi.fn() }));
vi.mock('@/lib/api', () => ({ api: { help: apiMocks } }));

describe('HelpSearchPage', () => {
  afterEach(() => { cleanup(); vi.clearAllMocks(); });
  it('preserves the query and renders official search results', async () => {
    apiMocks.search.mockResolvedValue(demoHelpSearch('agent'));
    render(<MemoryRouter initialEntries={['/help/search?q=agent']}><HelpSearchPage /></MemoryRouter>);
    expect(await screen.findByText(/Results for “agent”/)).toBeInTheDocument();
    expect(screen.getByDisplayValue('agent')).toBeInTheDocument();
  });
});
