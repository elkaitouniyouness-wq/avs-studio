"use client";
import { useEffect, useState } from "react";
import { api, useApi } from "../../lib/api";
import { LANGS } from "../../lib/i18n";
import { Card, Chips, Field, Select, Shell, Toggle, useI18n } from "../../lib/ui";

const KEYS: [string, string][] = [["gemini", "Google Gemini — GRATUIT (scripts + voix) : aistudio.google.com/apikey"], ["anthropic", "Anthropic (scripts, SEO)"], ["google_tts", "Google Cloud TTS (voix)"], ["pexels", "Pexels (images/clips)"], ["openai", "OpenAI TTS (voix de secours, optionnel)"], ["youtube_api", "YouTube Data API (tendances, optionnel)"]];

export default function Settings() {
  const { t, lang, setLang, theme, setTheme } = useI18n();
  const s = useApi<any>("/settings");
  const keys = useApi<any>("/keys");
  const opts = useApi<any>("/options");
  const [f, setF] = useState<any>(null);
  const [kv, setKv] = useState<Record<string, string>>({});
  const [msg, setMsg] = useState("");
  useEffect(() => { if (s.data && !f) setF(s.data); }, [s.data]);
  if (!f || !opts.data) return <Shell title={t("settings")}><div className="msg">{t("loading")}</div></Shell>;
  const set = (k: string, v: any) => setF({ ...f, [k]: v });
  const setD = (k: string, v: any) => setF({ ...f, defaults: { ...f.defaults, [k]: v } });
  const o = opts.data;
  async function save() {
    try { await api("/settings", { method: "PUT", body: f }); setMsg("✓"); } catch (e: any) { setMsg("⚠ " + e.message); }
  }
  async function saveKeys() {
    const body: any = {};
    Object.entries(kv).forEach(([k, v]) => { if (v !== undefined && v !== "") body[k] = v; });
    if (!Object.keys(body).length) return;
    await api("/keys", { method: "PUT", body });
    setKv({});
    keys.reload();
    setMsg("✓");
  }
  return (
    <Shell title={t("settings")}>
      <Card>
        <Field label={t("ui_language")}><Chips value={lang} onChange={setLang} options={LANGS.map((l) => [l.code, l.label])} /></Field>
        <Field label={t("theme")}><Chips value={theme} onChange={setTheme} options={[["dark", t("dark")], ["light", t("light")]]} /></Field>
        <Field label={t("timezone")}><input type="text" value={f.timezone} onChange={(e) => set("timezone", e.target.value)} /></Field>
        <Toggle checked={f.expert_mode} onChange={(v) => set("expert_mode", v)} label={t("expert")} />
      </Card>
      <Card title={t("create")}>
        <Field label={t("language")}><Select value={f.defaults.language} onChange={(v) => setD("language", v)} options={Object.entries(o.languages) as [string, string][]} /></Field>
        <Field label={t("format")}><Chips value={f.defaults.format} onChange={(v) => setD("format", v)} options={o.formats.map((x: string) => [x, x])} /></Field>
        <Field label={t("resolution")}><Chips value={f.defaults.resolution} onChange={(v) => setD("resolution", v)} options={o.resolutions.map((x: string) => [x, x])} /></Field>
        <Field label={t("duration")}><Chips value={f.defaults.duration} onChange={(v) => setD("duration", v)} options={o.durations.map((d: number) => [d, d < 120 ? `${d}s` : `${d / 60}min`])} /></Field>
        <Field label={t("voice")}><Chips value={f.defaults.voice_gender} onChange={(v) => setD("voice_gender", v)} options={[["male", t("male")], ["female", t("female")]]} /></Field>
        <Field label={t("voice_style")}><Select value={f.defaults.voice_style} onChange={(v) => setD("voice_style", v)} options={o.voice_styles.map((x: string) => [x, x.replace("_", " ")])} /></Field>
        <Field label={t("style")}><Select value={f.defaults.style} onChange={(v) => setD("style", v)} options={o.styles.map((x: string) => [x, x])} /></Field>
        <Toggle checked={f.defaults.subtitles} onChange={(v) => setD("subtitles", v)} label={t("subtitles")} />
        <Toggle checked={f.defaults.music} onChange={(v) => setD("music", v)} label={t("music")} />
      </Card>
      <Card title={t("budgets")}>
        <Field label={t("per_video")}><input type="number" step="0.05" min="0" value={f.max_budget_per_video} onChange={(e) => set("max_budget_per_video", Number(e.target.value))} /></Field>
        <Field label={t("per_day")}><input type="number" step="0.5" min="0" value={f.daily_budget} onChange={(e) => set("daily_budget", Number(e.target.value))} /></Field>
        <Field label={t("per_month")}><input type="number" step="1" min="0" value={f.monthly_budget} onChange={(e) => set("monthly_budget", Number(e.target.value))} /></Field>
        <small className="hint">La production s'arrête automatiquement quand un budget est atteint.</small>
      </Card>
      <Card title={t("publish_mode")}>
        <Chips value={f.publish_mode} onChange={(v) => set("publish_mode", v)} options={[["manual", t("manual")], ["auto", t("auto")]]} />
        <Toggle checked={f.auto_block_on_claims} onChange={(v) => set("auto_block_on_claims", v)} label={t("block_claims")} />
        <Toggle checked={f.script_review} onChange={(v) => set("script_review", v)} label={t("script_review")} />
        <Toggle checked={!!f.declare_ai_content} onChange={(v) => set("declare_ai_content", v)} label={t("declare_ai")} />
      </Card>
      <button className="btn" onClick={save}>💾 {t("save")}</button>

      <Card title={t("api_keys")}>
        {KEYS.map(([k, label]) => (
          <Field key={k} label={`${label} — ${keys.data?.[k] ? t("key_set") + " (" + keys.data[k] + ")" : t("key_missing")}`}>
            <input type="password" autoComplete="off" placeholder="••••••••" value={kv[k] || ""} onChange={(e) => setKv({ ...kv, [k]: e.target.value })} />
          </Field>
        ))}
        <button className="btn sec" onClick={saveKeys}>🔑 {t("save")}</button>
        <small className="hint">Les clés ne sont jamais renvoyées au navigateur. Laisser vide = inchangé.</small>
      </Card>
      <Card title={t("install_pwa")}><div>{t("pwa_android")}</div><div>{t("pwa_ios")}</div></Card>
      {msg && <div className="msg">{msg}</div>}
      <button className="btn sec" onClick={() => api("/auth/logout", { body: {} }).then(() => (location.href = "/login"))}>{t("logout")}</button>
    </Shell>
  );
}
