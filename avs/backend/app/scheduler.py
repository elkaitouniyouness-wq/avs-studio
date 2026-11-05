"""Planificateur : toutes les 30 s, lance les productions dues. Un seul processus scheduler doit tourner."""
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from . import options as O
from .db import SessionLocal, init_db
from .models import Schedule, User, Video
from .pipeline import fingerprint, spent_since, user_settings
from .costs import estimate
from .queue import enqueue


def due(s: Schedule, tz: str, now_utc: datetime | None = None) -> bool:
    now = (now_utc or datetime.now(ZoneInfo("UTC"))).astimezone(ZoneInfo(tz))
    if not s.enabled or now.weekday() not in (s.weekdays or []):
        return False
    if s.last_run_date == now.strftime("%Y-%m-%d"):
        return False
    return (now.hour, now.minute) >= (s.hour, s.minute)


def tick(db) -> int:
    started = 0
    for s in db.query(Schedule).filter(Schedule.enabled.is_(True)).all():
        user = db.get(User, s.user_id)
        st = user_settings(user)
        tz = st.get("timezone", "Africa/Casablanca")
        if st.get("paused") or not due(s, tz):
            continue
        now_local = datetime.now(ZoneInfo(tz))
        s.last_run_date = now_local.strftime("%Y-%m-%d")  # marqué avant : jamais deux lancements le même jour
        db.commit()
        params = {**O.DEFAULT_PARAMS, **st.get("defaults", {}), **s.params}
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        for _ in range(s.videos_per_run):
            if spent_since(db, user.id, today) + estimate(params)["total"] > float(st["daily_budget"]):
                break
            v = Video(user_id=user.id, schedule_id=s.id, niche=params.get("niche", ""), topic="", params=params, steps=s.steps, privacy=params.get("privacy", "private"),
                      channel_id=params.get("channel_id"), auto_publish=bool(params.get("auto_publish", False)))
            db.add(v)
            db.commit()
            try:
                enqueue("app.pipeline.run_video", v.id)
                started += 1
            except Exception as e:  # noqa: BLE001
                v.status, v.error = "failed", str(e)
                db.commit()
    return started


def main():
    init_db()
    while True:
        db = SessionLocal()
        try:
            tick(db)
        except Exception as e:  # noqa: BLE001
            print("scheduler error:", e, flush=True)
        finally:
            db.close()
        time.sleep(30)


if __name__ == "__main__":
    main()
