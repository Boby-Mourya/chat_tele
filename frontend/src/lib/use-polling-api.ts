import { useCallback, useEffect, useRef, useState } from 'react';
import type { AsyncState } from '@/lib/use-api';

/** Keep the last successful result visible while serial background requests run. */
export function usePollingApi<T>(
  loader: (signal: AbortSignal) => Promise<T>,
  dependencies: readonly unknown[],
  interval = 3000,
): AsyncState<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const refreshRef = useRef<() => void>(() => {});
  const reload = useCallback(() => refreshRef.current(), []);

  useEffect(() => {
    let active = true;
    let pending = false;
    let refreshAgain = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let controller: AbortController | undefined;

    const refresh = async () => {
      clearTimeout(timer);
      if (!active) return;
      if (pending) { refreshAgain = true; return; }
      pending = true;
      controller = new AbortController();
      try {
        const next = await loader(controller.signal);
        if (active) { setData(next); setError(null); }
      } catch (reason) {
        if (active && !controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : 'Could not update conversations');
        }
      } finally {
        pending = false;
        if (active) {
          setLoading(false);
          if (refreshAgain) {
            refreshAgain = false;
            void refresh();
          } else if (!document.hidden) {
            timer = setTimeout(() => void refresh(), interval);
          }
        }
      }
    };
    const resume = () => { if (!document.hidden) void refresh(); };
    const visibilityChanged = () => {
      if (document.hidden) clearTimeout(timer);
      else resume();
    };
    refreshRef.current = () => { void refresh(); };
    document.addEventListener('visibilitychange', visibilityChanged);
    window.addEventListener('focus', resume);
    window.addEventListener('online', resume);
    void refresh();
    return () => {
      active = false;
      clearTimeout(timer);
      controller?.abort();
      document.removeEventListener('visibilitychange', visibilityChanged);
      window.removeEventListener('focus', resume);
      window.removeEventListener('online', resume);
    };
    // The caller supplies the scope dependencies, as with useApi.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...dependencies, interval]);

  return { data, loading, error, reload };
}
