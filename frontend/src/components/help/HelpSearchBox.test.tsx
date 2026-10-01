import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { HelpSearchBox } from '@/components/help/HelpSearchBox';

const apiMocks = vi.hoisted(() => ({ search: vi.fn() }));
vi.mock('@/lib/api', () => ({ api: { help: apiMocks } }));
function Location() { return <span data-testid="location">{useLocation().pathname}{useLocation().search}</span>; }

describe('HelpSearchBox', () => {
  afterEach(() => { cleanup(); vi.clearAllMocks(); });
  it('submits search into the /help route family', async () => {
    const user = userEvent.setup(); apiMocks.search.mockResolvedValue({ items: [] });
    render(<MemoryRouter initialEntries={['/help']}><Routes><Route path="*" element={<><HelpSearchBox /><Location /></>} /></Routes></MemoryRouter>);
    await user.type(screen.getByRole('searchbox', { name: 'Search Northstar Help' }), 'WhatsApp setup');
    await user.click(screen.getByRole('button', { name: 'Search' }));
    expect(screen.getByTestId('location')).toHaveTextContent('/help/search?q=WhatsApp%20setup');
  });
});
