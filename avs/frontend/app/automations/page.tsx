"use client";
import { useState } from "react";
import { api, useApi } from "../../lib/api";
import { Card, Chips, Field, Select, Shell, Toggle, useI18n } from "../../lib/ui";

const blank = { name: "", enabled: true, hour: 9, minute: 0, weekdays: [0, 1, 2, 3, 4, 5, 6], videos_per_run: 1, on_error: "retry", niche: "", preset: "", channel_id: "", privacy: "private", auto_publish: false, language: "fr" };

export default function Automations() {
  const { t } = useI18n();
  const list = useApi<any[]>("/schedules", 10000);
  const opts = useApi<any>("/options");
  const channels = useApi<any[]>("/channels");
  const [f, setF] = useState<any>(null);
  const [editId, setEditId] = useState<number | null>(null);
  const [err, setErr] = useState("");
  const days = t("weekdays").split(",");

  async function save() {
    setErr("");
    const preset = opts.data?.presets[f.preset] || opts.data?.profiles.find((p: any) => p.name === f.preset)?.params || {};
    const body = { name: f.name || "Auto", enabled: f.enabled, hour: f.hour, minute: f.minute, weekdays: f.weekdays, videos_per_run: f.videos_per_run, on_error: f.on_error,
      params: { ...preset, language: f.language, niche: f.niche, privacy: f.privacy, auto_publish: f.auto_publish, channel_id: f.channel_id ? Number(f.channel_id) : null } };
    try {
      await api(editId ? `/schedules/${editId}` : "/schedules", { method: editId ? "PUT" : "POST", body });
      setF(null); setEditId(null); list.reload();
    } catch (e: any) { setErr(e.message); }
  }
  const edit = (s: any) => { setEditId(s.id); setF({ ...blank, name: s.name, enabled: s.enabled, hour: s.hour, minute: s.minute, weekdays: s.weekdays, videos_per_run: s.videos_per_run, on_error: s.on_error, niche: s.params.niche || "", channel_id: s.params.channel_id ? String(s.params.channel_id) : "", privacy: s.params.privacy || "private", auto_publish: !!s.params.auto_publish, language: s.params.language || "fr", preset: "" }); };

  return (
    <Shell title={t("automations")}>
      <small className="hint">Pipeline : tendances → sujet → script → voix → médias → montage → SEO → contrôle qualité → validation → publication → notification. Activez/désactivez les modules dans « Créer » (mode expert).</small>
      {list.data?.map((s) => (
        <Card key={s.id}>
          <div className="row" style={{ background: "none", padding: 0 }}>
            <div className="grow"><div className="rt">{s.name}</div><div className="rs">{String(s.hour).padStart(2, "0")}:{String(s.minute).padStart(2, "0")} · {s.weekdays.length}/7 · ×{s.videos_per_run} · {s.params.niche}</div>{s.last_run_date && <div className="rs">{t("last_run")}: {s.last_run_date}</div>}</div>
            <Toggle checked={s.enabled} label="" onChange={(v) => api(`/schedules/${s.id}`, { method: "PUT", body: { ...s, enabled: v } }).then(list.reload)} />
          </div>
          <div className="grid2">
            <button className="btn sec sm" onClick={() => edit(s)}>✏️</button>
            <button className="btn sec sm" onClick={() => confirm("OK ?") && api(`/schedules/${s.id}`, { method: "DELETE" }).then(list.reload)}>🗑</button>
          </div>
        </Card>
      ))}
      {!f && <button className="btn" onClick={() => { setEditId(null); setF({ ...blank }); }}>＋ {t("new_schedule")}</button>}
      {f && (
        <Card title={t("new_schedule")}>
          <Field label={t("name")}><input type="text" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
          <Field label={t("niche")}><input type="text" value={f.niche} onChange={(e) => setF({ ...f, niche: e.target.value })} /></Field>
          <Field label={t("presets")}><Select value={f.preset} onChange={(v) => setF({ ...f, preset: v })} options={[["", "—"], ...(Object.keys(opts.data?.presets || {}).map((k) => [k, k]) as [string, string][]), ...((opts.data?.profiles || []).map((p: any) => [p.name, "⭐ " + p.name]) as [string, string][])]} /></Field>
          <Field label={t("language")}><Select value={f.language} onChange={(v) => setF({ ...f, language: v })} options={Object.entries(opts.data?.languages || {}) as [string, string][]} /></Field>
          <Field label={t("time")}><input type="time" value={`${String(f.hour).padStart(2, "0")}:${String(f.minute).padStart(2, "0")}`} onChange={(e) => { const [h, m] = e.target.value.split(":").map(Number); setF({ ...f, hour: h || 0, minute: m || 0 }); }} /></Field>
          <Field label={t("days")}><div className="chips">{days.map((d: string, i: number) => <button type="button" key={i} className={f.weekdays.includes(i) ? "chip on" : "chip"} onClick={() => setF({ ...f, weekdays: f.weekdays.includes(i) ? f.weekdays.filter((x: number) => x !== i) : [...f.weekdays, i] })}>{d}</button>)}</div></Field>
          <Field label={t("per_run")}><input type="number" min={1} max={10} value={f.videos_per_run} onChange={(e) => setF({ ...f, videos_per_run: Number(e.target.value) })} /></Field>
          <Field label={t("channel")}><Select value={f.channel_id} onChange={(v) => setF({ ...f, channel_id: v })} options={[["", "—"], ...((channels.data || []).map((c) => [String(c.id), c.title]) as [string, string][])]} /></Field>
          <Field label={t("privacy")}><Chips value={f.privacy} onChange={(v) => setF({ ...f, privacy: v })} options={[["private", t("private")], ["unlisted", t("unlisted")], ["public", t("public")]]} /></Field>
          <Toggle checked={f.auto_publish} onChange={(v) => setF({ ...f, auto_publish: v })} label={t("auto_publish")} />
          <Field label={t("on_error")}><Chips value={f.on_error} onChange={(v) => setF({ ...f, on_error: v })} options={[["retry", t("retry")], ["stop", t("stop")]]} /></Field>
          <Toggle checked={f.enabled} onChange={(v) => setF({ ...f, enabled: v })} label={t("enabled")} />
          {err && <div className="msg bad-t">{err}</div>}
          <button className="btn" onClick={save}>{t("save")}</button>
          <button className="btn sec" onClick={() => setF(null)}>{t("cancel")}</button>
        </Card>
      )}
    </Shell>
  );
}
