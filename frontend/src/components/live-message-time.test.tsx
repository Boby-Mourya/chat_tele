import { act, cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { LiveMessageTime } from './live-message-time';

afterEach(() => { cleanup(); vi.useRealTimers(); });

it('advances elapsed time without an API refresh and accepts a new message time', () => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date('2026-09-30T10:00:00Z'));
  const { rerender } = render(<LiveMessageTime value="2026-09-30T10:00:00Z" />);
  expect(screen.getByText('just now')).toBeInTheDocument();
  act(() => vi.advanceTimersByTime(5000));
  expect(screen.getByText('5s ago')).toBeInTheDocument();
  act(() => vi.advanceTimersByTime(55000));
  expect(screen.getByText('1m ago')).toBeInTheDocument();
  rerender(<LiveMessageTime value="2026-09-30T10:01:00Z" />);
  expect(screen.getByText('just now')).toBeInTheDocument();
});
