"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import React, { createContext, useContext, useEffect, useState } from "react";
import { Lang, t as tr } from "./i18n";
import { api } from "./api";

type Ctx = { lang: Lang; setLang: (l: Lang) => void; theme: string; setTheme: (t: string) => void; t: (k: string) => string };
const I18n = createContext<Ctx>({ lang: "fr", setLang() {}, theme: "dark", setTheme() {}, t: (k) => k });
export const useI18n = () => useContext(I18n);

function safeGet(k: string) {
  try { return localStorage.getItem(k); } catch { return null; }
}
function safeSet(k: string, v: string) {
  try { localStorage.setItem(k, v); } catch {}
}

export function Providers({ children }: { children: React.ReactNode }) {
  const [lang, setLangS] = useState<Lang>("fr");
  const [theme, setThemeS] = useState("dark");
  useEffect(() => {
    const l = (safeGet("avs_lang") as Lang) || "fr";
    const th = safeGet("avs_theme") || "dark";
    setLangS(l);
    setThemeS(th);
    if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
  }, []);
  useEffect(() => {
    document.documentElement.lang = lang;
    document.documentElement.dir = lang === "ar" ? "rtl" : "ltr";
    document.documentElement.dataset.theme = theme;
  }, [lang, theme]);
  const setLang = (l: Lang) => { setLangS(l); safeSet("avs_lang", l); api("/settings", { method: "PUT", body: { ui_lang: l } }).catch(() => {}); };
  const setTheme = (x: string) => { setThemeS(x); safeSet("avs_theme", x); api("/settings", { method: "PUT", body: { theme: x } }).catch(() => {}); };
  return <I18n.Provider value={{ lang, setLang, theme, setTheme, t: (k) => tr(k, lang) }}>{children}</I18n.Provider>;
}

const NAV = [
  { href: "/", key: "home", icon: "🏠" },
  { href: "/create", key: "create", icon: "✨" },
  { href: "/videos", key: "videos", icon: "🎬" },
  { href: "/automations", key: "automations", icon: "⚙️" },
  { href: "/settings", key: "settings", icon: "🛠️" },
];

export function Shell({ children, title }: { children: React.ReactNode; title?: string }) {
  const { t } = useI18n();
  const path = usePathname();
  return (
    <div className="shell">
      <header className="top">
        <strong>{title || t("app")}</strong>
        <Link href="/channels" className="chip" aria-label={t("channels")}>📺 {t("channels")}</Link>
      </header>
      <main className="main">{children}</main>
      <nav className="tabs">
        {NAV.map((n) => (
          <Link key={n.href} href={n.href} className={(n.href === "/" ? path === "/" : path.startsWith(n.href)) ? "tab on" : "tab"}>
            <span className="ico">{n.icon}</span>
            <span>{t(n.key)}</span>
          </Link>
        ))}
      </nav>
    </div>
  );
}

// ---------- composants de formulaire (grands, tactiles) ----------
export function Field({ label, children, hint }: { label: string; children: React.ReactNode; hint?: string }) {
  return (
    <label className="field">
      <span className="lbl">{label}</span>
      {children}
      {hint && <small className="hint">{hint}</small>}
    </label>
  );
}
export function Select({ value, onChange, options }: { value: any; onChange: (v: string) => void; options: [string, string][] }) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)}>
      {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
    </select>
  );
}
export function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <label className="toggle">
      <input type="checkbox" checked={!!checked} onChange={(e) => onChange(e.target.checked)} />
      <span>{label}</span>
    </label>
  );
}
export function Chips({ value, onChange, options }: { value: any; onChange: (v: any) => void; options: [any, string][] }) {
  return (
    <div className="chips">
      {options.map(([v, l]) => (
        <button type="button" key={String(v)} className={value === v ? "chip on" : "chip"} onClick={() => onChange(v)}>{l}</button>
      ))}
    </div>
  );
}
export function Card({ title, children, tone }: { title?: string; children: React.ReactNode; tone?: string }) {
  return (
    <section className={"card " + (tone || "")}>
      {title && <h3>{title}</h3>}
      {children}
    </section>
  );
}
export function Badge({ status }: { status: string }) {
  const { t } = useI18n();
  return <span className={"badge b-" + status}>{t(status)}</span>;
}
export function Progress({ value }: { value: number }) {
  return <div className="bar"><div style={{ width: `${Math.max(0, Math.min(100, value))}%` }} /></div>;
}
export function VideoRow({ v }: { v: any }) {
  return (
    <Link href={`/videos/${v.id}`} className="row">
      <div className="grow">
        <div className="rt">{v.title || `#${v.id}`}</div>
        <div className="rs">#{v.id} · {v.params?.duration}s · {v.params?.format} · ${v.cost_total?.toFixed(3)}</div>
        {(v.status === "running" || v.status === "queued") && <Progress value={v.progress} />}
        {v.error && v.status === "failed" && <div className="err">{v.error}</div>}
      </div>
      <Badge status={v.status} />
    </Link>
  );
}
