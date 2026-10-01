import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { PageErrorBoundary } from './PageErrorBoundary';

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

function BrokenPage(): never { throw new Error('private implementation detail'); }

it('provides recovery actions without exposing an internal error and resets on navigation', () => {
  vi.spyOn(console, 'error').mockImplementation(() => undefined);
  const { rerender } = render(<PageErrorBoundary key="first"><BrokenPage /></PageErrorBoundary>);
  expect(screen.getByRole('alert')).toHaveTextContent('This page couldn’t load');
  expect(screen.getByRole('button', { name: 'Refresh page' })).toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'Back to workspace' })).toHaveAttribute('href', '/');
  expect(screen.queryByText('private implementation detail')).not.toBeInTheDocument();
  rerender(<PageErrorBoundary key="second"><p>Healthy page</p></PageErrorBoundary>);
  expect(screen.getByText('Healthy page')).toBeInTheDocument();
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});
