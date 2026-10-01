import { useEffect, useRef, useState } from "react";

/** Polls `fetcher` every `intervalMs` until `isDone` returns true, or the component unmounts. */
export function usePolling<T>(fetcher: () => Promise<T>, isDone: (value: T) => boolean, intervalMs = 1200, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const timer = useRef<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const value = await fetcher();
        if (cancelled) return;
        setData(value);
        if (!isDone(value)) {
          timer.current = window.setTimeout(tick, intervalMs);
        }
      } catch (err) {
        if (!cancelled) setError(err as Error);
      }
    };
    tick();
    return () => {
      cancelled = true;
      if (timer.current) window.clearTimeout(timer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { data, error };
}
