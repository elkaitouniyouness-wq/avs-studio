"use client";
import { useCallback, useEffect, useRef, useState } from "react";

export async function api<T = any>(path: string, opts: { method?: string; body?: any; raw?: BodyInit; contentType?: string; blob?: boolean } = {}): Promise<T> {
  const headers: Record<string, string> = {};
  let body: BodyInit | undefined;
  if (opts.raw !== undefined) {
    body = opts.raw;
    if (opts.contentType) headers["Content-Type"] = opts.contentType;
  } else if (opts.body !== undefined) {
    body = JSON.stringify(opts.body);
    headers["Content-Type"] = "application/json";
  }
  const r = await fetch("/api" + path, { method: opts.method || (body ? "POST" : "GET"), headers, body, credentials: "same-origin" });
  if (r.status === 401 && !location.pathname.startsWith("/login")) {
    location.href = "/login";
    throw new Error("401");
  }
  if (!r.ok) {
    let msg = r.statusText;
    try {
      const j = await r.json();
      msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch {}
    throw new Error(msg);
  }
  if (opts.blob) return (await r.blob()) as any;
  return (await r.json()) as T;
}

/** GET périodique. `refreshMs` > 0 : rafraîchit automatiquement (suivi des tâches en cours). */
export function useApi<T = any>(path: string | null, refreshMs = 0) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const alive = useRef(true);
  const load = useCallback(async () => {
    if (!path) return;
    try {
      const d = await api<T>(path);
      if (alive.current) {
        setData(d);
        setError(null);
      }
    } catch (e: any) {
      if (alive.current) setError(e.message);
    }
  }, [path]);
  useEffect(() => {
    alive.current = true;
    load();
    if (!refreshMs) return () => { alive.current = false; };
    const id = setInterval(load, refreshMs);
    return () => {
      alive.current = false;
      clearInterval(id);
    };
  }, [load, refreshMs]);
  return { data, error, reload: load, setData };
}
