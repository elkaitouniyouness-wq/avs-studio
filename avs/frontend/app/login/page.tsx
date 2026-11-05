"use client";
import { useState } from "react";
import { api } from "../../lib/api";
import { Field, useI18n } from "../../lib/ui";
import { LANGS } from "../../lib/i18n";

export default function Login() {
  const { t, lang, setLang } = useI18n();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr("");
    try {
      await api("/auth/login", { body: { email, password } });
      location.href = "/";
    } catch (e: any) {
      setErr(e.message);
      setBusy(false);
    }
  }
  return (
    <form className="login" onSubmit={submit}>
      <h1>🎬 {t("app")}</h1>
      <div className="chips">
        {LANGS.map((l) => <button type="button" key={l.code} className={lang === l.code ? "chip on" : "chip"} onClick={() => setLang(l.code)}>{l.label}</button>)}
      </div>
      <Field label={t("email")}><input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" required /></Field>
      <Field label={t("password")}><input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required /></Field>
      {err && <div className="msg bad-t">{err}</div>}
      <button className="btn" disabled={busy}>{t("login")}</button>
    </form>
  );
}
