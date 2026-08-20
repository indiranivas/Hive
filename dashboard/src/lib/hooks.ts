"use client";

import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import { ApiError } from "./api";

interface AsyncState<T> {
  data: T | null;
  error: string | null;
  detail?: string;
  loading: boolean;
  reload: () => void;
}

interface Settled<T> {
  key: string;
  data: T | null;
  error: string | null;
  detail?: string;
}

/** Fetch on mount and whenever `deps` change.
 *
 *  `loading` is derived by comparing the settled result's key with the current
 *  one rather than being set at the top of the effect: state is only written
 *  from the async callbacks, which keeps cascading renders (and the
 *  react-hooks/set-state-in-effect rule) out of it. The same key comparison
 *  discards a slow response that resolves after a newer request. */
export function useApi<T>(loader: () => Promise<T>, deps: unknown[] = []): AsyncState<T> {
  const [nonce, setNonce] = useState(0);
  const key = `${JSON.stringify(deps)}#${nonce}`;
  const [settled, setSettled] = useState<Settled<T> | null>(null);

  useEffect(() => {
    let active = true;
    loader()
      .then((result) => {
        if (active) setSettled({ key, data: result, error: null });
      })
      .catch((caught: unknown) => {
        if (!active) return;
        setSettled({
          key,
          data: null,
          error: caught instanceof Error ? caught.message : "Something went wrong",
          detail: caught instanceof ApiError ? caught.detail : undefined,
        });
      });
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const reload = useCallback(() => setNonce((value) => value + 1), []);
  const current = settled?.key === key ? settled : null;

  return {
    data: current?.data ?? settled?.data ?? null,
    error: current?.error ?? null,
    detail: current?.detail,
    loading: current === null,
    reload,
  };
}

const THEME_EVENT = "hive-theme-change";

function subscribeToTheme(onChange: () => void) {
  window.addEventListener(THEME_EVENT, onChange);
  return () => window.removeEventListener(THEME_EVENT, onChange);
}

/** The theme lives on <html data-theme>, written before first paint by the inline
 *  script in the layout. Reading it through useSyncExternalStore avoids both a
 *  hydration mismatch and a setState-in-effect. */
function readTheme(): "light" | "dark" | null {
  const value = document.documentElement.dataset.theme;
  return value === "light" || value === "dark" ? value : null;
}

export function useTheme() {
  const theme = useSyncExternalStore(
    subscribeToTheme,
    readTheme,
    () => null, // server render: no stored preference is knowable
  );

  const toggle = useCallback(() => {
    const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    const current = readTheme() ?? (prefersDark ? "dark" : "light");
    const next = current === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try {
      window.localStorage.setItem("hive-theme", next);
    } catch {
      // private mode or storage disabled: the toggle still works for this session
    }
    window.dispatchEvent(new Event(THEME_EVENT));
  }, []);

  return { theme, toggle };
}
