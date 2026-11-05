"use client";
import { useEffect, useState } from "react";
import { api, useApi } from "../../lib/api";
import { Card, Shell, useI18n } from "../../lib/ui";

export default function Channels() {
  const { t } = useI18n();
  const list = useApi<any[]>("/channels");
  const opts = useApi<any>("/options");
  const [msg, setMsg] = useState("");
  useEffect(() => {
    const q = new URLSearchParams(location.search);
    if (q.get("connected")) setMsg("✓ OK");
    if (q.get("error")) setMsg("⚠ " + q.get("error"));
  }, []);
  async function connect() {
    try { const r = await api("/youtube/connect"); location.href = r.url; } catch (e: any) { setMsg("⚠ " + e.message); }
  }
  return (
    <Shell title={t("channels")}>
      {list.data?.map((c) => (
        <Card key={c.id}><div className="row" style={{ background: "none", padding: 0 }}><div className="grow rt">📺 {c.title}</div>
          <button className="btn sec sm" onClick={() => confirm("OK ?") && api(`/channels/${c.id}`, { method: "DELETE" }).then(list.reload)}>🗑</button></div></Card>
      ))}
      {list.data?.length === 0 && <div className="msg">{t("nothing")}</div>}
      <button className="btn" onClick={connect} disabled={opts.data && !opts.data.youtube_oauth}>🔗 {t("connect_yt")}</button>
      {opts.data && !opts.data.youtube_oauth && <div className="msg warn-t">GOOGLE_OAUTH_CLIENT_ID / SECRET non configurés côté serveur (voir docs/DEPLOIEMENT.md).</div>}
      <small className="hint">{t("oauth_note")}</small>
      <small className="hint">Si la chaîne est dans un compte à plusieurs chaînes, choisissez-la sur l'écran Google. Tant que votre projet Google Cloud n'a pas passé l'audit YouTube, les vidéos envoyées par l'API restent forcées en « privé ».</small>
      {msg && <div className="msg">{msg}</div>}
    </Shell>
  );
}
