import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { ToastProvider } from '@/components/providers';
import { HelpArticlePage } from '@/pages/HelpArticlePage';
import { demoHelpArticle, demoHelpHome } from '@/lib/help-demo-data';

const apiMocks = vi.hoisted(() => ({ article: vi.fn(), home: vi.fn(), feedback: vi.fn() }));
vi.mock('@/lib/api', () => ({ api: { help: apiMocks } }));

describe('HelpArticlePage', () => {
  afterEach(() => { cleanup(); vi.clearAllMocks(); localStorage.clear(); });
  it('renders breadcrumbs, safe markdown, feedback, and support', async () => {
    apiMocks.article.mockResolvedValue(demoHelpArticle('create-agent'));
    apiMocks.home.mockResolvedValue(demoHelpHome());
    apiMocks.feedback.mockResolvedValue(undefined);
    render(<MemoryRouter initialEntries={['/help/articles/create-agent']}><ToastProvider><Routes><Route path="/help/articles/:slug" element={<HelpArticlePage />} /></Routes></ToastProvider></MemoryRouter>);
    expect((await screen.findAllByRole('heading', { name: /Create.*agent/i })).length).toBeGreaterThan(0);
    expect(screen.getByText(/Was this helpful/i)).toBeInTheDocument();
    expect(screen.getByText('Still need help?')).toBeInTheDocument();
  });
});
