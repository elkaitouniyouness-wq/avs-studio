"use client";
import { useState } from "react";
import { api, useApi } from "../../lib/api";
import { Chips, Shell, VideoRow, useI18n } from "../../lib/ui";

export default function Videos() {
  const { t } = useI18n();
  const [f, setF] = useState("");
  const { data, reload } = useApi<any[]>(`/videos?limit=100${f ? "&status=" + f : ""}`, 5000);
  return (
    <Shell title={t("videos")}>
      <Chips value={f} onChange={setF} options={[["", "Tout"], ["running", t("running")], ["ready", t("ready")], ["published", t("published")], ["failed", t("failed")]]} />
      {!data && <div className="msg">{t("loading")}</div>}
      {data?.length === 0 && <div className="msg">{t("nothing")}</div>}
      {data?.map((v) => <VideoRow key={v.id} v={v} />)}
      {data && data.length > 0 && (
        <button className="btn sec" onClick={async () => {
          if (!confirm("Supprimer tout l'historique (vidéos prêtes, échouées, annulées) et leurs fichiers ? Les vidéos en cours et celles déjà publiées sur YouTube sont conservées.")) return;
          try { const r = await api("/videos", { method: "DELETE" }); alert(`${r.deleted} vidéo(s) supprimée(s)`); reload(); } catch (e: any) { alert("⚠ " + e.message); }
        }}>🗑 Vider l'historique</button>
      )}
    </Shell>
  );
}
