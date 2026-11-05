"use client";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { api, useApi } from "../../../lib/api";
import { Badge, Card, Chips, Field, Progress, Select, Shell, useI18n } from "../../../lib/ui";

export default function VideoPage() {
  const { t } = useI18n();
  const { id } = useParams<{ id: string }>();
  const { data: v, reload, error } = useApi<any>(`/videos/${id}`, 3000);
  const channels = useApi<any[]>("/channels");
  const [scenes, setScenes] = useState<any[] | null>(null);
  const [seo, setSeo] = useState<any>(null);
  const [dirty, setDirty] = useState(false);
  const [msg, setMsg] = useState("");
  const [pubAt, setPubAt] = useState("");
  const [pubCh, setPubCh] = useState("");
  const [pubPriv, setPubPriv] = useState("private");

  useEffect(() => {
    if (!v || dirty) return;
    setScenes(v.scenes.map((s: any) => ({ ...s })));
    setSeo({ ...v.seo, tagsText: (v.seo?.tags || []).join(", ") });
    if (!pubCh && v.channel_id) setPubCh(String(v.channel_id));
    setPubPriv(v.privacy);
  }, [v?.status, v?.scenes?.length, JSON.stringify(v?.scenes?.map((x: any) => x.media?.id)), JSON.stringify(v?.seo?.title), dirty]);

  if (error) return <Shell><div className="msg bad-t">{error}</div></Shell>;
  if (!v || !scenes) return <Shell><div className="msg">{t("loading")}</div></Shell>;
  const active = ["queued", "running", "publishing"].includes(v.status);
  const run = async (fn: () => Promise<any>, ok = "") => {
    setMsg("");
    try { await fn(); setMsg(ok); setDirty(false); reload(); } catch (e: any) { setMsg("⚠ " + e.message); }
  };
  const save = () => run(() => api(`/videos/${id}`, { method: "PATCH", body: {
    scenes: scenes.map((s) => ({ i: s.i, narration: s.narration, visual_query: s.visual_query })),
    seo: { title: seo.title, description: seo.description, tags: seo.tagsText.split(",").map((x: string) => x.trim()).filter(Boolean) },
  } }), "✓");
  const regen = (stage: string) => api(`/videos/${id}/regenerate`, { body: { from_stage: stage } });
  const saveAll = async () => {
    await api(`/videos/${id}`, { method: "PATCH", body: {
      scenes: scenes.map((s) => ({ i: s.i, narration: s.narration, visual_query: s.visual_query })),
      seo: { title: seo.title, description: seo.description, tags: seo.tagsText.split(",").map((x: string) => x.trim()).filter(Boolean) },
    } });
    await regen("voice");
  };
  const changeChannel = (val: string) => {
    setPubCh(val);
    run(() => api(`/videos/${id}`, { method: "PATCH", body: val ? { channel_id: Number(val) } : { clear_channel: true } }), "✓");
  };
  const upload = (i: number, file: File) => run(() => api(`/videos/${id}/scenes/${i}/media`, { method: "PUT", raw: file, contentType: file.type }), "✓");
  const qc = v.qc || {};

  return (
    <Shell title={`#${v.id}`}>
      <Card>
        <div className="row" style={{ background: "none", padding: 0 }}>
          <div className="grow rt">{v.title}</div><Badge status={v.status} />
        </div>
        {active && <><Progress value={v.progress} /><small className="hint">{v.stage}</small></>}
        {v.error && <div className="err">{v.error}</div>}
        {v.has_video && <video src={`/api/videos/${id}/file`} controls playsInline preload="metadata" poster={v.has_thumb ? `/api/videos/${id}/thumb` : undefined} />}
        {v.has_video && <div className="grid2">
          <a className="btn sec" href={`/api/videos/${id}/download`}>⬇ {t("download")} MP4</a>
          <a className="btn sec" href={`/api/videos/${id}/srt`}>⬇ SRT</a>
        </div>}
        {v.has_thumb && <img className="thumb" alt="thumbnail" src={`/api/videos/${id}/thumb`} />}
      </Card>

      {!v.youtube_video_id && (
        <Card title="📺 Compte / chaîne YouTube">
          <Select value={pubCh} onChange={changeChannel} options={[["", "— aucune —"], ...((channels.data || []).map((c) => [String(c.id), c.title]) as [string, string][])]} />
          <small className="hint">Vous pouvez changer de compte à tout moment avant la publication. {(channels.data || []).length === 0 && <>Aucun compte connecté : <a href="/channels">connecter un compte YouTube</a>.</>}</small>
        </Card>
      )}

      {(qc.errors?.length > 0 || qc.warnings?.length > 0 || v.claims?.length > 0) && (
        <Card title={t("quality")} tone={qc.errors?.length ? "bad" : "warn"}>
          {qc.errors?.map((e: string, i: number) => <div key={i} className="bad-t">✗ {e}</div>)}
          {qc.warnings?.map((e: string, i: number) => <div key={i} className="warn-t">⚠ {e}</div>)}
          {v.claims?.length > 0 && <><strong>{t("claims")}</strong>{v.claims.map((c: string, i: number) => <div key={i}>• {c}</div>)}</>}
        </Card>
      )}
      {qc.ok && <div className="msg ok-t">✓ {t("quality")}</div>}

      <Card title={t("script")}>
        {scenes.map((s, k) => (
          <div className="scene" key={s.i}>
            <strong>#{s.i + 1}{s.dur ? ` · ${s.dur.toFixed(1)}${t("seconds")}` : ""}</strong>
            {s.media && (s.media.kind === "video" ? <video src={`/api/videos/${id}/scenes/${s.i}/media`} muted playsInline controls /> : <img alt="" src={`/api/videos/${id}/scenes/${s.i}/media`} />)}
            {s.media?.card && <small className="warn-t">Aucun média trouvé : carte de remplacement</small>}
            {s.media?.credit && <small className="hint">© {s.media.credit} (Pexels)</small>}
            <Field label={t("narration")}><textarea value={s.narration} disabled={active} onChange={(e) => { setDirty(true); setScenes(scenes.map((x, j) => (j === k ? { ...x, narration: e.target.value } : x))); }} /></Field>
            <Field label={t("visual_query")}><input type="text" value={s.visual_query} disabled={active} onChange={(e) => { setDirty(true); setScenes(scenes.map((x, j) => (j === k ? { ...x, visual_query: e.target.value } : x))); }} /></Field>
            <label className="chip" style={{ justifySelf: "start" }}>📷 {t("replace_media")}
              <input type="file" accept="image/jpeg,image/png,image/webp,video/mp4" hidden disabled={active} onChange={(e) => e.target.files?.[0] && upload(s.i, e.target.files[0])} />
            </label>
          </div>
        ))}
      </Card>

      <Card title={t("seo")}>
        {seo?.titles?.length > 1 && <Chips value={seo.title} onChange={(x) => { setDirty(true); setSeo({ ...seo, title: x }); }} options={seo.titles.map((x: string) => [x, x.slice(0, 40)])} />}
        <Field label={t("title")}><input type="text" maxLength={100} value={seo?.title || ""} disabled={active} onChange={(e) => { setDirty(true); setSeo({ ...seo, title: e.target.value }); }} /></Field>
        <Field label={t("description")}><textarea style={{ minHeight: 160 }} value={seo?.description || ""} disabled={active} onChange={(e) => { setDirty(true); setSeo({ ...seo, description: e.target.value }); }} /></Field>
        <Field label={t("tags")}><input type="text" value={seo?.tagsText || ""} disabled={active} onChange={(e) => { setDirty(true); setSeo({ ...seo, tagsText: e.target.value }); }} /></Field>
        {seo?.thumbnail_idea && <small className="hint">💡 {seo.thumbnail_idea}</small>}
      </Card>
      <button className="btn" disabled={active || !dirty} onClick={save}>💾 {t("save")}</button>
      {!v.youtube_video_id && <button className="btn sec" disabled={active || !dirty} onClick={() => run(saveAll, "✓")}>🔄 Enregistrer + tout régénérer (voix, montage, description, tags, miniature)</button>}
      {dirty && <small className="hint">Après modification de la narration, utilisez « {t("regenerate")} » → voix pour refaire l'audio et le montage.</small>}

      {!active && !v.youtube_video_id && (
        <Card title={t("regenerate")}>
          <div className="chips">
            {[["script", "Script"], ["voice", "Voix"], ["media", "Médias"], ["render", "Montage"], ["seo", "Description + tags + miniature"]].map(([s, l]) => (
              <button key={s} className="chip" onClick={() => confirm("OK ?") && run(() => api(`/videos/${id}/regenerate`, { body: { from_stage: s } }))}>{l}</button>
            ))}
          </div>
        </Card>
      )}

      {(v.status === "ready" || v.status === "failed") && qc.ok && !v.youtube_video_id && (
        <Card title={t("publish")}>
          <Field label={t("channel")}><Select value={pubCh} onChange={setPubCh} options={[["", "—"], ...((channels.data || []).map((c) => [String(c.id), c.title]) as [string, string][])]} /></Field>
          <Chips value={pubPriv} onChange={setPubPriv} options={[["private", t("private")], ["unlisted", t("unlisted")], ["public", t("public")]]} />
          <Field label={t("schedule_at")}><input type="datetime-local" value={pubAt} onChange={(e) => setPubAt(e.target.value)} /></Field>
          <button className="btn ok" onClick={() => run(() => api(`/videos/${id}/publish`, { body: { privacy: pubPriv, channel_id: pubCh ? Number(pubCh) : null, publish_at: pubAt ? new Date(pubAt).toISOString() : null } }))}>▶ {t("publish")}</button>
        </Card>
      )}
      {v.youtube_video_id && <a className="btn sec" href={`https://youtube.com/watch?v=${v.youtube_video_id}`} target="_blank" rel="noreferrer">▶ YouTube</a>}
      {active && <button className="btn bad" onClick={() => run(() => api(`/videos/${id}/cancel`, { body: {} }))}>{t("cancel")}</button>}
      {msg && <div className="msg">{msg}</div>}

      <Card title={t("costs")}>
        {Object.entries(v.costs || {}).map(([k, c]: any) => <div key={k} className="row"><div className="grow">{k}</div>${c.toFixed(4)}</div>)}
        <b>Total ≈ ${v.cost_total.toFixed(4)}</b>
        <small className="hint">Estimation basée sur les tarifs configurés ; vérifiez la facturation réelle chez chaque fournisseur.</small>
      </Card>
      <Card title={t("logs")}><div className="log">{v.logs.map((l: any) => `${l.at.slice(11, 19)} [${l.stage}] ${l.level}: ${l.message}`).join("\n")}</div></Card>
      {!active && <button className="btn sec" onClick={() => confirm("OK ?") && api(`/videos/${id}`, { method: "DELETE" }).then(() => (location.href = "/videos"))}>🗑 {t("delete")}</button>}
    </Shell>
  );
}
