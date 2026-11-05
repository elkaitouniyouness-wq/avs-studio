"use client";
import Link from "next/link";
import { api, useApi } from "../lib/api";
import { Card, Progress, Shell, VideoRow, useI18n } from "../lib/ui";

export default function Dashboard() {
  const { t } = useI18n();
  const stats = useApi<any>("/stats", 5000);
  const vids = useApi<any[]>("/videos?limit=6", 5000);
  const notes = useApi<any[]>("/notifications", 10000);
  const s = stats.data;
  const by = s?.by_status || {};
  const running = (by.running || 0) + (by.queued || 0) + (by.publishing || 0);

  async function kill() {
    await api("/kill-switch", { body: { on: !s.paused } });
    stats.reload();
  }
  return (
    <Shell>
      {!s && <div className="msg">{t("loading")}</div>}
      {s && (
        <>
          {s.paused && <Card tone="bad"><strong className="bad-t">⏸ {t("paused")}</strong></Card>}
          <div className="grid2">
            <div className="stat"><b>{running}</b><span>{t("running")}</span></div>
            <div className="stat"><b>{by.ready || 0}</b><span>{t("ready")}</span></div>
            <div className="stat"><b>{by.published || 0}</b><span>{t("published")}</span></div>
            <div className="stat"><b className={by.failed ? "bad-t" : ""}>{by.failed || 0}</b><span>{t("failed")}</span></div>
          </div>
          <Link href="/create" className="btn" style={{ textAlign: "center" }}>✨ {t("new_video")}</Link>
          <Card title={t("budget_today")}>
            <div>${s.spent_today.toFixed(3)} / ${s.daily_budget}</div>
            <Progress value={(s.spent_today / s.daily_budget) * 100} />
            <small className="hint">{t("budget_month")} : ${s.spent_month.toFixed(2)} / ${s.monthly_budget}</small>
          </Card>
          {s.upcoming.length > 0 && <Card title={t("upcoming")}>{s.upcoming.map((v: any) => <div key={v.id} className="row"><div className="grow rt">{v.title}</div><small>{new Date(v.publish_at).toLocaleString()}</small></div>)}</Card>}
          {s.recent_errors.length > 0 && <Card title={t("recent_errors")} tone="bad">{s.recent_errors.map((v: any) => <VideoRow key={v.id} v={v} />)}</Card>}
          <Card title={t("recent_videos")}>
            {vids.data?.length ? vids.data.map((v) => <VideoRow key={v.id} v={v} />) : <div className="hint">{t("nothing")}</div>}
          </Card>
          <Card title={`${t("notifications")}`}>
            {notes.data?.length ? notes.data.slice(0, 6).map((n) => <div key={n.id} className="msg">{n.message}<br /><small className="hint">{new Date(n.at + "Z").toLocaleString()}</small></div>) : <div className="hint">{t("nothing")}</div>}
          </Card>
          <button className={"btn big-kill " + (s.paused ? "ok" : "bad")} onClick={kill}>{s.paused ? "▶ " + t("kill_off") : "⛔ " + t("kill_on")}</button>
          <small className="hint">{t("stats_note")}</small>
        </>
      )}
    </Shell>
  );
}
