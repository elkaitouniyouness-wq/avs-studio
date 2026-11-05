"use client";
import { useEffect, useRef, useState } from "react";
import { api, useApi } from "../../lib/api";
import { Card, Chips, Field, Select, Shell, Toggle, useI18n } from "../../lib/ui";

const STEP_LABELS: Record<string, string> = { script: "Script IA", voice: "Voix off", media: "Images & clips", render: "Montage", subtitles: "Sous-titres", seo: "SEO", thumbnail: "Miniature", qc: "Contrôle qualité", publish: "Publication auto" };

export default function Create() {
  const { t, lang } = useI18n();
  const opts = useApi<any>("/options");
  const settings = useApi<any>("/settings");
  const channels = useApi<any[]>("/channels");
  const [p, setP] = useState<any>(null);
  const [niche, setNiche] = useState("");
  const [topic, setTopic] = useState("");
  const [ideas, setIdeas] = useState<any[]>([]);
  const [trend, setTrend] = useState<boolean | null>(null);
  const [steps, setSteps] = useState<string[]>(["script", "voice", "media", "render", "subtitles", "seo", "thumbnail", "qc"]);
  const [channelId, setChannelId] = useState("");
  const [privacy, setPrivacy] = useState("private");
  const [auto, setAuto] = useState(false);
  const [est, setEst] = useState<any>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [customDur, setCustomDur] = useState(false);
  const audio = useRef<HTMLAudioElement>(null);

  useEffect(() => { if (settings.data && !p) setP({ ...settings.data.defaults }); }, [settings.data]);
  useEffect(() => {
    if (!p) return;
    const id = setTimeout(() => api("/estimate", { body: p }).then(setEst).catch(() => setEst(null)), 400);
    return () => clearTimeout(id);
  }, [JSON.stringify(p)]);

  if (!opts.data || !p) return <Shell title={t("new_video")}><div className="msg">{t("loading")}</div></Shell>;
  const o = opts.data;
  const set = (k: string, v: any) => setP((x: any) => ({ ...x, [k]: v }));

  async function findIdeas() {
    setErr("");
    try {
      const r = await api("/ideas", { body: { niche, category: p.category, language: p.language, count: 6 } });
      setIdeas(r.ideas);
      setTrend(r.trend_data_available);
    } catch (e: any) { setErr(e.message); }
  }
  async function preview() {
    try {
      const blob = await api<Blob>("/voice/preview", { body: p, blob: true });
      if (audio.current) { audio.current.src = URL.createObjectURL(blob); audio.current.play(); }
    } catch (e: any) { setErr(e.message); }
  }
  async function launch() {
    setBusy(true);
    setErr("");
    try {
      const v = await api("/videos", { body: { niche, topic, params: p, steps, privacy, auto_publish: auto, channel_id: channelId ? Number(channelId) : null } });
      location.href = `/videos/${v.id}`;
    } catch (e: any) { setErr(e.message); setBusy(false); }
  }
  async function saveProfile() {
    const name = prompt(t("save_profile"));
    if (name) { await api("/profiles", { body: { name, params: p } }); opts.reload(); }
  }
  const langOpts = Object.entries(o.languages) as [string, string][];
  const durations: number[] = o.durations;
  const fmtLabel = (f: string) => ({ "9:16": "9:16 Shorts", "16:9": "16:9", "1:1": "1:1" } as any)[f] || f;

  return (
    <Shell title={t("new_video")}>
      <Card title={t("presets")}>
        <div className="chips">
          {Object.entries(o.presets).map(([n, v]: any) => <button key={n} className="chip" onClick={() => setP((x: any) => ({ ...x, ...v }))}>{n}</button>)}
          {o.profiles.map((pr: any) => <button key={pr.id} className="chip" onClick={() => setP((x: any) => ({ ...x, ...pr.params }))}>⭐ {pr.name}</button>)}
        </div>
      </Card>

      <Card>
        <Field label={t("niche")}><input type="text" value={niche} onChange={(e) => setNiche(e.target.value)} placeholder="ex: faits étonnants sur l'espace" /></Field>
        <Field label={t("category")}><Select value={p.category} onChange={(v) => set("category", v)} options={o.categories.map((c: string) => [c, c.replace("_", " ")])} /></Field>
        <button className="btn sec" onClick={findIdeas} disabled={!niche}>💡 {t("find_ideas")}</button>
        {trend !== null && <small className="hint">{trend ? t("trend_ok") : t("trend_no")}</small>}
        {ideas.map((i, k) => <button key={k} className="row" style={{ textAlign: "start", border: 0 }} onClick={() => { setTopic(i.topic); setIdeas([]); }}><div className="grow"><div className="rt">{i.topic}</div><div className="rs">{i.angle}</div></div></button>)}
        <Field label={t("topic")}><input type="text" value={topic} onChange={(e) => setTopic(e.target.value)} /></Field>
      </Card>

      <Card>
        <Field label={t("language")}><Select value={p.language} onChange={(v) => set("language", v)} options={langOpts} /></Field>
        <Field label={t("duration")}>
          <Chips value={customDur ? -1 : p.duration} onChange={(v) => { if (v === -1) setCustomDur(true); else { setCustomDur(false); set("duration", v); } }}
            options={[...durations.map((d) => [d, d < 120 ? `${d}${t("seconds")}` : `${d / 60} min`] as [any, string]), [-1, t("custom")]]} />
          {customDur && <input type="number" min={5} max={1800} value={p.duration} onChange={(e) => set("duration", Number(e.target.value))} />}
        </Field>
        <Field label={t("format")}><Chips value={p.format} onChange={(v) => set("format", v)} options={o.formats.map((f: string) => [f, fmtLabel(f)])} /></Field>
        <Field label={t("resolution")}><Chips value={p.resolution} onChange={(v) => set("resolution", v)} options={o.resolutions.map((r: string) => [r, r])} /></Field>
        <Field label={t("style")}><Select value={p.style} onChange={(v) => set("style", v)} options={o.styles.map((s: string) => [s, s])} /></Field>
      </Card>

      <Card title={t("voice")}>
        <Chips value={p.voice_gender} onChange={(v) => set("voice_gender", v)} options={[["male", t("male")], ["female", t("female")]]} />
        <Field label={t("voice_style")}><Select value={p.voice_style} onChange={(v) => set("voice_style", v)} options={o.voice_styles.map((s: string) => [s, s.replace("_", " ")])} /></Field>
        <Field label={`${t("speed")} : ${p.voice_speed}×`}><input type="range" min={0.8} max={1.3} step={0.05} value={p.voice_speed} onChange={(e) => set("voice_speed", Number(e.target.value))} /></Field>
        <button className="btn sec" onClick={preview}>🔊 {t("preview_voice")}</button>
        <audio ref={audio} controls style={{ width: "100%" }} />
        {p.language === "ary" && <small className="hint">Darija : le texte est écrit en darija, la voix est une voix arabe standard (aucun fournisseur ne propose de voix marocaine native).</small>}
        <Toggle checked={p.subtitles} onChange={(v) => set("subtitles", v)} label={t("subtitles")} />
        <Toggle checked={p.music} onChange={(v) => set("music", v)} label={t("music")} />
        <Toggle checked={p.draft} onChange={(v) => set("draft", v)} label={t("draft")} />
      </Card>

      <Card title={t("channel")}>
        <Select value={channelId} onChange={setChannelId} options={[["", "—"], ...((channels.data || []).map((c) => [String(c.id), c.title]) as [string, string][])]} />
        <Field label={t("privacy")}><Chips value={privacy} onChange={setPrivacy} options={[["private", t("private")], ["unlisted", t("unlisted")], ["public", t("public")]]} /></Field>
        <Toggle checked={auto} onChange={setAuto} label={t("auto_publish")} />
        {auto && settings.data?.publish_mode !== "auto" && <small className="warn-t">Réglages → Mode de publication est sur « manuel » : l'auto-publication restera désactivée.</small>}
      </Card>

      {settings.data?.expert_mode && (
        <Card title={t("steps")}>
          {Object.keys(STEP_LABELS).map((s) => (
            <Toggle key={s} label={STEP_LABELS[s]} checked={steps.includes(s) || o.required_steps.includes(s)} onChange={(v) => !o.required_steps.includes(s) && setSteps((x) => (v ? [...x, s] : x.filter((y) => y !== s)))} />
          ))}
          <small className="hint">Script, voix, médias et montage sont obligatoires ; l'ordre est fixe (chaque étape dépend de la précédente).</small>
        </Card>
      )}

      {est && <Card title={t("estimate")}><b>≈ ${est.total.toFixed(3)}</b><small className="hint">script ${est.script} · voix ${est.audio} · SEO ${est.seo} · médias Pexels $0 · rendu $0 (serveur)</small></Card>}
      {err && <div className="msg bad-t">{err}</div>}
      <button className="btn" onClick={launch} disabled={busy}>🚀 {t("launch")}</button>
      <button className="btn sec" onClick={saveProfile}>⭐ {t("save_profile")}</button>
    </Shell>
  );
}
