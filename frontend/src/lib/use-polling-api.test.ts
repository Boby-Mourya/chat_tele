import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { usePollingApi } from '@/lib/use-polling-api';

describe('background API updates', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.spyOn(document, 'hidden', 'get').mockReturnValue(false);
  });
  afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); });

  it('updates an initially empty result without blanking the current data', async () => {
    const loader = vi.fn().mockResolvedValueOnce([]).mockResolvedValueOnce(['new conversation']);
    const { result } = renderHook(() => usePollingApi(loader, []));
    await act(async () => {});
    expect(result.current.data).toEqual([]);
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    expect(result.current.data).toEqual(['new conversation']);
    expect(result.current.loading).toBe(false);
  });

  it('allows slow requests to finish and never overlaps background requests', async () => {
    let finish!: (value: string[]) => void;
    const loader = vi.fn().mockImplementationOnce(() => new Promise<string[]>((resolve) => { finish = resolve; }))
      .mockResolvedValue(['fresh']);
    const { result } = renderHook(() => usePollingApi(loader, []));
    await act(async () => { await vi.advanceTimersByTimeAsync(15000); });
    expect(loader).toHaveBeenCalledTimes(1);
    act(() => { result.current.reload(); result.current.reload(); });
    expect(loader).toHaveBeenCalledTimes(1);
    await act(async () => { finish(['old']); });
    expect(loader).toHaveBeenCalledTimes(2);
    expect(result.current.data).toEqual(['fresh']);
  });

  it('keeps the last messages on failure and recovers automatically', async () => {
    const loader = vi.fn().mockResolvedValueOnce(['message'])
      .mockRejectedValueOnce(new Error('Offline')).mockResolvedValueOnce(['message', 'reply']);
    const { result } = renderHook(() => usePollingApi(loader, []));
    await act(async () => {});
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    expect(result.current.data).toEqual(['message']);
    expect(result.current.error).toBe('Offline');
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    expect(result.current.data).toEqual(['message', 'reply']);
    expect(result.current.error).toBeNull();
  });

  it('pauses hidden tabs and refreshes immediately on return or reconnection', async () => {
    const loader = vi.fn().mockResolvedValue([]);
    renderHook(() => usePollingApi(loader, []));
    await act(async () => {});
    vi.spyOn(document, 'hidden', 'get').mockReturnValue(true);
    act(() => { document.dispatchEvent(new Event('visibilitychange')); });
    await act(async () => { await vi.advanceTimersByTimeAsync(30000); });
    expect(loader).toHaveBeenCalledTimes(1);
    vi.spyOn(document, 'hidden', 'get').mockReturnValue(false);
    await act(async () => { document.dispatchEvent(new Event('visibilitychange')); });
    expect(loader).toHaveBeenCalledTimes(2);
    await act(async () => { window.dispatchEvent(new Event('online')); });
    expect(loader).toHaveBeenCalledTimes(3);
  });

  it('cancels the old scope and ignores stale results after filters change', async () => {
    let finish!: (value: string) => void;
    const loader = vi.fn().mockImplementationOnce(() => new Promise<string>((resolve) => { finish = resolve; }))
      .mockResolvedValue('new workspace');
    const { result, rerender, unmount } = renderHook(
      ({ scope }) => usePollingApi(loader, [scope]), { initialProps: { scope: 'old' } },
    );
    const oldSignal = loader.mock.calls[0]![0] as AbortSignal;
    rerender({ scope: 'new' });
    await act(async () => {});
    expect(oldSignal.aborted).toBe(true);
    await act(async () => { finish('old workspace'); });
    expect(result.current.data).toBe('new workspace');
    unmount();
    await act(async () => { await vi.advanceTimersByTimeAsync(30000); });
    expect(loader).toHaveBeenCalledTimes(2);
  });
});
