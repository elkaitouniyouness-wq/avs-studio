import time
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from . import options as O
from .config import get_settings
from .costs import estimate
from .db import get_db, init_db, SessionLocal
from .keys import KEY_NAMES, env_keys, resolve_keys
from .models import Channel, JobLog, Notification, Profile, Schedule, User, Video
from .pipeline import fingerprint, spent_since, user_settings
from .queue import QueueError, enqueue
from .security import create_token, decode_token, decrypt_json, encrypt, encrypt_json, hash_password, verify_password
from .services import tts, youtube

COOKIE = "avs_session"
WEAK = {"dev-secret-change-me", "change-me-long-random-string", ""}
_fails: dict[str, list[float]] = defaultdict(list)


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    if s.cookie_secure and s.app_secret_key in WEAK:
        raise RuntimeError("APP_SECRET_KEY doit être défini à une valeur aléatoire longue (voir .env.example)")
    if s.app_encryption_key:
        from cryptography.fernet import Fernet

        try:
            Fernet(s.app_encryption_key.encode())
        except Exception as e:
            raise RuntimeError("APP_ENCRYPTION_KEY invalide : générez-la avec `python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"`") from e
    elif s.cookie_secure:
        raise RuntimeError("APP_ENCRYPTION_KEY manquante (chiffrement des clés API et jetons YouTube)")
    init_db()
    Path(s.media_dir).mkdir(parents=True, exist_ok=True)
    db = SessionLocal()
    try:
        if s.admin_email and s.admin_password and not db.query(User).count():
            if s.admin_password.startswith("change-me"):
                raise RuntimeError("ADMIN_PASSWORD doit être changé (voir .env.example)")
            db.add(User(email=s.admin_email.lower(), password_hash=hash_password(s.admin_password), settings=dict(O.DEFAULT_SETTINGS)))
            db.commit()
    finally:
        db.close()
    yield


app = FastAPI(title="AI Video Automation Studio", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[get_settings().frontend_origin], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    data = decode_token(request.cookies.get(COOKIE, ""))
    user = db.get(User, int(data["sub"])) if data else None
    if not user:
        raise HTTPException(401, "Non authentifié")
    return user


def own_video(db: Session, user: User, vid: int) -> Video:
    v = db.get(Video, vid)
    if not v or v.user_id != user.id:
        raise HTTPException(404, "Vidéo introuvable")
    return v


def video_dict(v: Video, full: bool = False) -> dict:
    d = {
        "id": v.id, "niche": v.niche, "topic": v.topic, "status": v.status, "stage": v.stage, "progress": v.progress, "error": v.error,
        "title": (v.seo or {}).get("title") or (v.seo or {}).get("working_title") or v.topic, "cost_total": v.cost_total, "privacy": v.privacy,
        "publish_at": v.publish_at.isoformat() if v.publish_at else None, "auto_publish": v.auto_publish, "channel_id": v.channel_id,
        "youtube_video_id": v.youtube_video_id, "duration": v.duration_actual, "has_video": bool(v.video_path and Path(v.video_path).exists()),
        "has_thumb": bool(v.thumb_path and Path(v.thumb_path).exists()), "created_at": v.created_at.isoformat(), "params": v.params,
        "qc": v.qc, "retries": v.retries,
    }
    if full:
        d.update(script=v.script, claims=v.claims, seo=v.seo, costs=v.costs, steps=v.steps,
                 scenes=[{k: x for k, x in s.items() if k not in ("audio_voice",)} | {"media": {k: m for k, m in (s.get("media") or {}).items() if k != "path"}} for s in v.scenes],
                 logs=[{"stage": l.stage, "level": l.level, "message": l.message, "at": l.created_at.isoformat()} for l in v.logs[-80:]])
    return d


def naive_utc(dt: datetime | None) -> datetime | None:
    """Les dates sont stockées en UTC sans fuseau (évite les décalages selon la base)."""
    if dt is not None and dt.tzinfo is not None:
        from datetime import timezone

        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def dispatch(fn: str, vid: int):
    try:
        enqueue(fn, vid)
    except QueueError as e:
        db = SessionLocal()
        try:
            v = db.get(Video, vid)
            if v:
                v.status, v.error = "failed", str(e)
                db.commit()
        finally:
            db.close()
        raise HTTPException(503, str(e))


# ---------- Santé & options ----------
@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/options")
def options(user: User = Depends(current_user), db: Session = Depends(get_db)):
    profiles = [{"id": p.id, "name": p.name, "params": p.params} for p in db.query(Profile).filter(Profile.user_id == user.id)]
    return {
        "durations": O.DURATIONS, "formats": list(O.FORMATS), "resolutions": list(O.RESOLUTIONS), "languages": O.VIDEO_LANGS, "styles": O.STYLES,
        "categories": O.CATEGORIES, "voice_styles": O.VOICE_STYLES, "steps": O.STEP_ORDER, "required_steps": O.REQUIRED_STEPS,
        "presets": O.PRESETS, "profiles": profiles, "youtube_oauth": youtube.configured(),
    }


# ---------- Auth ----------
class LoginIn(BaseModel):
    email: str
    password: str


@app.post("/api/auth/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    ip = request.client.host if request.client else "?"
    _fails[ip] = [t for t in _fails[ip] if time.time() - t < 600]
    if len(_fails[ip]) >= 5:
        raise HTTPException(429, "Trop de tentatives, réessayez dans 10 minutes")
    user = db.query(User).filter(User.email == body.email.lower().strip()).first()
    if not user or not verify_password(body.password, user.password_hash):
        _fails[ip].append(time.time())
        raise HTTPException(401, "Identifiants incorrects")
    response.set_cookie(COOKIE, create_token(user.id), httponly=True, secure=get_settings().cookie_secure, samesite="lax", max_age=7 * 86400, path="/")
    return {"email": user.email}


@app.post("/api/auth/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@app.get("/api/auth/me")
def me(user: User = Depends(current_user)):
    return {"email": user.email, "settings": user_settings(user)}


# ---------- Paramètres & clés ----------
@app.get("/api/settings")
def get_settings_route(user: User = Depends(current_user)):
    return user_settings(user)


@app.put("/api/settings")
def put_settings(body: dict, user: User = Depends(current_user), db: Session = Depends(get_db)):
    cur = user_settings(user)
    allowed = set(O.DEFAULT_SETTINGS) | {"declare_ai_content"}
    for k, v in body.items():
        if k not in allowed:
            continue
        if k == "defaults":
            v = {**cur.get("defaults", {}), **{a: b for a, b in v.items() if a in O.DEFAULT_PARAMS}}
        if k in ("max_budget_per_video", "daily_budget", "monthly_budget"):
            v = max(0.0, float(v))
        cur[k] = v
    user.settings = cur
    db.commit()
    return cur


@app.get("/api/keys")
def get_keys(user: User = Depends(current_user)):
    stored, env = decrypt_json(user.api_keys_enc), env_keys()
    return {k: ("user" if stored.get(k) else "env" if env.get(k) else None) for k in KEY_NAMES}


@app.put("/api/keys")
def put_keys(body: dict, user: User = Depends(current_user), db: Session = Depends(get_db)):
    stored = decrypt_json(user.api_keys_enc)
    for k, v in body.items():
        if k in KEY_NAMES:
            if v:
                stored[k] = str(v).strip()
            else:
                stored.pop(k, None)
    user.api_keys_enc = encrypt_json(stored)
    db.commit()
    return get_keys(user)


# ---------- Idées, estimation, aperçu voix ----------
def merged_params(user: User, extra: dict) -> dict:
    p = {**O.DEFAULT_PARAMS, **user_settings(user).get("defaults", {}), **extra}
    p["duration"] = int(p["duration"])
    if not 5 <= p["duration"] <= 1800:
        raise HTTPException(422, "Durée : 5 à 1800 secondes")
    if p["format"] not in O.FORMATS or p["resolution"] not in O.RESOLUTIONS or p["language"] not in O.VIDEO_LANGS:
        raise HTTPException(422, "Format, résolution ou langue invalide")
    if p["voice_gender"] not in ("male", "female") or p["voice_style"] not in O.VOICE_STYLES:
        raise HTTPException(422, "Voix invalide")
    return p


@app.post("/api/estimate")
def estimate_route(body: dict, user: User = Depends(current_user)):
    return estimate(merged_params(user, body))


class IdeasIn(BaseModel):
    niche: str
    category: str = "facts"
    language: str = "fr"
    count: int = 6


@app.post("/api/ideas")
def ideas(body: IdeasIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    from .services import llm, trends

    keys = resolve_keys(user)
    recent = [t for (t,) in db.query(Video.topic).filter(Video.user_id == user.id, Video.topic != "").order_by(Video.id.desc()).limit(40)]
    signals = trends.trend_titles(keys.get("youtube_api", ""), body.language)
    try:
        lkey, lmodel = llm.pick_llm(keys, get_settings().script_model)
        res, i, o = llm.gen_ideas(lkey, lmodel, body.niche, body.category, body.language, min(body.count, 10), recent, signals)
    except llm.LLMError as e:
        raise HTTPException(400, str(e))
    return {"ideas": res, "trend_data_available": bool(signals)}


SAMPLES = {
    "ar": "مرحبا بكم! هذه عينة من الصوت الذي سيتم استخدامه في الفيديو الخاص بكم.",
    "ary": "مرحبا بيكم! هادي عينة ديال الصوت لي غادي نستعملو ف الفيديو ديالكم.",
    "fr": "Bonjour ! Voici un échantillon de la voix qui sera utilisée dans votre vidéo.",
    "en": "Hello! This is a sample of the voice that will be used in your video.",
    "es": "¡Hola! Esta es una muestra de la voz que se usará en tu vídeo.",
}


@app.post("/api/voice/preview")
def voice_preview(body: dict, user: User = Depends(current_user)):
    lang = body.get("language", "fr")
    voice = O.resolve_voice(lang, body.get("voice_gender", "male"), body.get("voice_style", "natural"), float(body.get("voice_speed", 1.0)))
    try:
        mp3, _ = tts.synthesize(resolve_keys(user), SAMPLES.get(lang, SAMPLES["en"]), voice)
    except tts.TTSError as e:
        raise HTTPException(400, str(e))
    return Response(mp3, media_type="audio/mpeg")


# ---------- Vidéos ----------
class VideoIn(BaseModel):
    niche: str = ""
    topic: str = ""
    params: dict = {}
    steps: list[str] | None = None
    auto_publish: bool = False
    privacy: str = "private"
    publish_at: datetime | None = None
    channel_id: int | None = None


def create_video(db: Session, user: User, body: VideoIn, schedule_id: int | None = None) -> Video:
    st = user_settings(user)
    if st.get("paused"):
        raise HTTPException(423, "Automatisations en pause (arrêt d'urgence actif)")
    if body.privacy not in ("public", "private", "unlisted"):
        raise HTTPException(422, "Confidentialité invalide")
    p = merged_params(user, body.params)
    steps = [s for s in O.STEP_ORDER if s in (body.steps or O.DEFAULT_STEPS) or s in O.REQUIRED_STEPS]
    if "qc" not in steps:
        steps.append("qc")
    if body.channel_id:
        ch = db.get(Channel, body.channel_id)
        if not ch or ch.user_id != user.id:
            raise HTTPException(404, "Chaîne introuvable")
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    if spent_since(db, user.id, today) + estimate(p)["total"] > float(st["daily_budget"]):
        raise HTTPException(402, "Budget journalier insuffisant pour cette vidéo")
    v = Video(user_id=user.id, channel_id=body.channel_id, schedule_id=schedule_id, niche=body.niche, topic=body.topic.strip(), params=p, steps=steps,
              auto_publish=body.auto_publish, privacy=body.privacy, publish_at=naive_utc(body.publish_at), fingerprint=fingerprint(body.topic, p["language"]))
    db.add(v)
    db.commit()
    return v


@app.post("/api/videos")
def post_video(body: VideoIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    v = create_video(db, user, body)
    dispatch("app.pipeline.run_video", v.id)
    return video_dict(v)


@app.get("/api/videos")
def list_videos(status: str | None = None, limit: int = 50, user: User = Depends(current_user), db: Session = Depends(get_db)):
    q = db.query(Video).filter(Video.user_id == user.id)
    if status:
        q = q.filter(Video.status == status)
    return [video_dict(v) for v in q.order_by(Video.id.desc()).limit(min(limit, 200))]


@app.get("/api/videos/{vid}")
def get_video(vid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return video_dict(own_video(db, user, vid), full=True)


class VideoPatch(BaseModel):
    scenes: list[dict] | None = None
    seo: dict | None = None
    privacy: str | None = None
    publish_at: datetime | None = None
    clear_publish_at: bool = False
    auto_publish: bool | None = None
    channel_id: int | None = None
    clear_channel: bool = False


@app.patch("/api/videos/{vid}")
def patch_video(vid: int, body: VideoPatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    v = own_video(db, user, vid)
    if v.status in ("running", "publishing"):
        raise HTTPException(409, "Vidéo en cours de traitement")
    if body.scenes is not None:
        by_i = {s["i"]: dict(s) for s in v.scenes}
        for s in body.scenes:
            cur = by_i.get(s.get("i"))
            if cur:
                cur["narration"] = str(s.get("narration", cur["narration"])).strip() or cur["narration"]
                cur["visual_query"] = str(s.get("visual_query", cur["visual_query"]))
        v.scenes = [by_i[k] for k in sorted(by_i)]
        v.script = "\n\n".join(s["narration"] for s in v.scenes)
    if body.seo is not None:
        seo = dict(v.seo or {})
        for k in ("title", "description", "tags", "hashtags", "thumbnail_text", "category", "file_name"):
            if k in body.seo:
                seo[k] = body.seo[k]
        if len(seo.get("title", "")) > 100:
            raise HTTPException(422, "Titre trop long (100 max)")
        v.seo = seo
    if body.privacy:
        if body.privacy not in ("public", "private", "unlisted"):
            raise HTTPException(422, "Confidentialité invalide")
        v.privacy = body.privacy
    if body.publish_at or body.clear_publish_at:
        v.publish_at = naive_utc(body.publish_at)
    if body.auto_publish is not None:
        v.auto_publish = body.auto_publish
    if body.channel_id is not None:
        ch = db.get(Channel, body.channel_id)
        if not ch or ch.user_id != user.id:
            raise HTTPException(404, "Chaîne introuvable")
        v.channel_id = body.channel_id
    elif body.clear_channel:
        v.channel_id = None
    db.commit()
    return video_dict(v, full=True)


class RegenIn(BaseModel):
    from_stage: str = "voice"


@app.post("/api/videos/{vid}/regenerate")
def regenerate(vid: int, body: RegenIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    v = own_video(db, user, vid)
    if v.status in ("running", "publishing") or v.youtube_video_id:
        raise HTTPException(409, "Régénération impossible (en cours ou déjà publiée)")
    order = O.STEP_ORDER
    if body.from_stage not in order:
        raise HTTPException(422, "Étape inconnue")
    k = order.index(body.from_stage)
    if k <= order.index("script"):
        v.script, v.scenes, v.claims, v.seo = "", [], [], {}
    if k <= order.index("voice"):
        v.scenes = [{kk: x for kk, x in s.items() if kk not in ("audio", "audio_text", "audio_voice", "dur_audio")} for s in v.scenes]
    if k <= order.index("media"):
        v.scenes = [s if (s.get("media") or {}).get("locked") else {kk: x for kk, x in s.items() if kk != "media"} for s in v.scenes]
    if k <= order.index("seo"):
        v.seo = {"working_title": (v.seo or {}).get("working_title", v.topic)}
    v.status, v.error, v.upload_url = "queued", None, None
    db.commit()
    dispatch("app.pipeline.run_video", v.id)
    return video_dict(v)


@app.post("/api/videos/{vid}/cancel")
def cancel(vid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    v = own_video(db, user, vid)
    v.cancel_requested = True
    if v.status == "queued":
        v.status = "cancelled"
    db.commit()
    return video_dict(v)


class PublishIn(BaseModel):
    privacy: str | None = None
    publish_at: datetime | None = None
    channel_id: int | None = None


@app.post("/api/videos/{vid}/publish")
def publish(vid: int, body: PublishIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    v = own_video(db, user, vid)
    if user_settings(user).get("paused"):
        raise HTTPException(423, "Automatisations en pause")
    if v.status not in ("ready", "failed") or not v.qc.get("ok"):
        raise HTTPException(409, "La vidéo doit être prête et avoir réussi le contrôle qualité")
    if body.privacy:
        v.privacy = body.privacy
    if body.publish_at:
        v.publish_at = naive_utc(body.publish_at)
    if body.channel_id:
        ch = db.get(Channel, body.channel_id)
        if not ch or ch.user_id != user.id:
            raise HTTPException(404, "Chaîne introuvable")
        v.channel_id = body.channel_id
    if not v.channel_id:
        raise HTTPException(422, "Choisissez une chaîne YouTube")
    v.status = "publishing"
    db.commit()
    dispatch("app.pipeline.run_publish", v.id)
    return video_dict(v)


@app.delete("/api/videos/{vid}")
def delete_video(vid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    import shutil

    v = own_video(db, user, vid)
    if v.status in ("running", "publishing"):
        raise HTTPException(409, "Vidéo en cours de traitement")
    shutil.rmtree(Path(get_settings().media_dir) / "videos" / str(v.id), ignore_errors=True)
    db.delete(v)
    db.commit()
    return {"ok": True}


@app.delete("/api/videos")
def delete_all_videos(status: str = "", user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Vide l'historique : supprime les vidéos TERMINÉES (prêtes, échouées, annulées) et leurs fichiers.
    Les vidéos en cours et celles déjà publiées sur YouTube sont conservées (sauf status=published demandé explicitement)."""
    import shutil

    q = db.query(Video).filter(Video.user_id == user.id, Video.status.notin_(["running", "queued", "publishing"]))
    if status:
        q = q.filter(Video.status == status)
    else:
        q = q.filter(Video.status != "published")
    n = 0
    for v in q.all():
        shutil.rmtree(Path(get_settings().media_dir) / "videos" / str(v.id), ignore_errors=True)
        db.delete(v)
        n += 1
    db.commit()
    return {"deleted": n}


# Fichiers (cookie de session requis, lecture par plages gérée par Starlette pour le lecteur vidéo)
@app.get("/api/videos/{vid}/file")
def video_file(vid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    v = own_video(db, user, vid)
    if not v.video_path or not Path(v.video_path).exists():
        raise HTTPException(404, "Pas de fichier")
    return FileResponse(v.video_path, media_type="video/mp4", filename=(v.seo or {}).get("file_name", f"video-{v.id}") + ".mp4", content_disposition_type="inline")


@app.get("/api/videos/{vid}/download")
def video_download(vid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    v = own_video(db, user, vid)
    if not v.video_path or not Path(v.video_path).exists():
        raise HTTPException(404, "Pas de fichier")
    return FileResponse(v.video_path, media_type="video/mp4", filename=(v.seo or {}).get("file_name", f"video-{v.id}") + ".mp4")


@app.get("/api/videos/{vid}/thumb")
def video_thumb(vid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    v = own_video(db, user, vid)
    if not v.thumb_path or not Path(v.thumb_path).exists():
        raise HTTPException(404, "Pas de miniature")
    return FileResponse(v.thumb_path, media_type="image/jpeg")


@app.get("/api/videos/{vid}/srt")
def video_srt(vid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    v = own_video(db, user, vid)
    f = Path(get_settings().media_dir) / "videos" / str(v.id) / "subs.srt"
    if not f.exists():
        raise HTTPException(404, "Pas de sous-titres")
    return FileResponse(str(f), media_type="application/x-subrip", filename=f"{(v.seo or {}).get('file_name', 'video')}.srt")


@app.get("/api/videos/{vid}/scenes/{i}/media")
def scene_media(vid: int, i: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    v = own_video(db, user, vid)
    s = next((x for x in v.scenes if x["i"] == i), None)
    m = (s or {}).get("media") or {}
    if not m.get("path") or not Path(m["path"]).exists():
        raise HTTPException(404, "Pas de média")
    return FileResponse(m["path"])


@app.put("/api/videos/{vid}/scenes/{i}/media")
async def replace_scene_media(vid: int, i: int, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Remplace le média d'une scène (corps = fichier brut, Content-Type image/jpeg|png|webp ou video/mp4)."""
    v = own_video(db, user, vid)
    if v.status in ("running", "publishing"):
        raise HTTPException(409, "Vidéo en cours de traitement")
    ctype = request.headers.get("content-type", "").split(";")[0]
    ext, kind = {"image/jpeg": (".jpg", "image"), "image/png": (".png", "image"), "image/webp": (".webp", "image"), "video/mp4": (".mp4", "video")}.get(ctype, (None, None))
    if not ext:
        raise HTTPException(415, "Type non supporté (jpeg, png, webp, mp4)")
    data = await request.body()
    if not data or len(data) > 80 * 1024 * 1024:
        raise HTTPException(413, "Fichier vide ou trop volumineux (80 Mo max)")
    scenes = [dict(s) for s in v.scenes]
    s = next((x for x in scenes if x["i"] == i), None)
    if not s:
        raise HTTPException(404, "Scène introuvable")
    dest = Path(get_settings().media_dir) / "videos" / str(v.id) / f"media_{i:02d}_custom{ext}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    s["media"] = {"kind": kind, "id": f"custom{i}", "path": str(dest), "credit": "", "locked": True, "query": s["visual_query"]}
    v.scenes = scenes
    db.commit()
    return video_dict(v, full=True)


# ---------- Planifications (workflows récurrents) & profils ----------
class ScheduleIn(BaseModel):
    name: str
    enabled: bool = True
    hour: int = 9
    minute: int = 0
    weekdays: list[int] = [0, 1, 2, 3, 4, 5, 6]
    videos_per_run: int = 1
    params: dict = {}
    steps: list[str] = O.DEFAULT_STEPS
    on_error: str = "retry"


def sched_dict(s: Schedule):
    return {"id": s.id, "name": s.name, "enabled": s.enabled, "hour": s.hour, "minute": s.minute, "weekdays": s.weekdays, "videos_per_run": s.videos_per_run, "params": s.params, "steps": s.steps, "on_error": s.on_error, "last_run_date": s.last_run_date}


def apply_schedule(s: Schedule, b: ScheduleIn):
    if not (0 <= b.hour < 24 and 0 <= b.minute < 60) or not 1 <= b.videos_per_run <= 10 or b.on_error not in ("retry", "stop"):
        raise HTTPException(422, "Paramètres de planification invalides")
    s.name, s.enabled, s.hour, s.minute, s.weekdays = b.name[:120], b.enabled, b.hour, b.minute, [d for d in b.weekdays if 0 <= d <= 6]
    s.videos_per_run, s.params, s.steps, s.on_error = b.videos_per_run, {**b.params, "on_error": b.on_error}, b.steps, b.on_error


@app.get("/api/schedules")
def list_schedules(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return [sched_dict(s) for s in db.query(Schedule).filter(Schedule.user_id == user.id)]


@app.post("/api/schedules")
def add_schedule(body: ScheduleIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    s = Schedule(user_id=user.id)
    apply_schedule(s, body)
    db.add(s)
    db.commit()
    return sched_dict(s)


@app.put("/api/schedules/{sid}")
def edit_schedule(sid: int, body: ScheduleIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    s = db.get(Schedule, sid)
    if not s or s.user_id != user.id:
        raise HTTPException(404, "Planification introuvable")
    apply_schedule(s, body)
    db.commit()
    return sched_dict(s)


@app.delete("/api/schedules/{sid}")
def del_schedule(sid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    s = db.get(Schedule, sid)
    if not s or s.user_id != user.id:
        raise HTTPException(404, "Planification introuvable")
    db.delete(s)
    db.commit()
    return {"ok": True}


@app.post("/api/profiles")
def save_profile(body: dict, user: User = Depends(current_user), db: Session = Depends(get_db)):
    name = str(body.get("name", "")).strip()[:120]
    if not name:
        raise HTTPException(422, "Nom requis")
    params = {k: v for k, v in body.get("params", {}).items() if k in O.DEFAULT_PARAMS}
    p = db.query(Profile).filter(Profile.user_id == user.id, Profile.name == name).first() or Profile(user_id=user.id, name=name)
    p.params = params
    db.add(p)
    db.commit()
    return {"id": p.id, "name": p.name, "params": p.params}


@app.delete("/api/profiles/{pid}")
def del_profile(pid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = db.get(Profile, pid)
    if p and p.user_id == user.id:
        db.delete(p)
        db.commit()
    return {"ok": True}


# ---------- YouTube ----------
@app.get("/api/youtube/connect")
def yt_connect(user: User = Depends(current_user)):
    try:
        return {"url": youtube.auth_url(create_token(user.id, "oauth", 600))}
    except youtube.YouTubeError as e:
        raise HTTPException(400, str(e))


@app.get("/api/youtube/callback")
def yt_callback(code: str = "", state: str = "", error: str = "", db: Session = Depends(get_db)):
    back = get_settings().frontend_origin.rstrip("/") + "/channels"
    data = decode_token(state, "oauth")
    if error or not code or not data:
        return RedirectResponse(f"{back}?error={quote(error or 'autorisation refusée')}")
    user = db.get(User, int(data["sub"]))
    try:
        tok = youtube.exchange_code(code)
        if not tok.get("refresh_token"):
            raise youtube.YouTubeError("Google n'a pas renvoyé de refresh token : révoquez l'accès de l'app dans votre compte Google puis réessayez")
        for c in youtube.my_channels(tok["access_token"]):
            ch = db.query(Channel).filter(Channel.user_id == user.id, Channel.youtube_channel_id == c["id"]).first() or Channel(user_id=user.id, youtube_channel_id=c["id"])
            ch.title, ch.refresh_token_enc = c["title"], encrypt(tok["refresh_token"])
            db.add(ch)
        db.commit()
    except youtube.YouTubeError as e:
        return RedirectResponse(f"{back}?error={quote(str(e))}")
    return RedirectResponse(f"{back}?connected=1")


@app.get("/api/channels")
def channels(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return [{"id": c.id, "title": c.title, "youtube_channel_id": c.youtube_channel_id} for c in db.query(Channel).filter(Channel.user_id == user.id)]


@app.delete("/api/channels/{cid}")
def del_channel(cid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = db.get(Channel, cid)
    if c and c.user_id == user.id:
        db.delete(c)
        db.commit()
    return {"ok": True}


# ---------- Stats, notifications, arrêt d'urgence ----------
@app.get("/api/stats")
def stats(user: User = Depends(current_user), db: Session = Depends(get_db)):
    now = datetime.utcnow()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    by_status = dict(db.query(Video.status, func.count()).filter(Video.user_id == user.id).group_by(Video.status).all())
    vids = db.query(Video).filter(Video.user_id == user.id, Video.created_at >= today - timedelta(days=13)).all()
    per_day = defaultdict(lambda: {"videos": 0, "cost": 0.0})
    for v in vids:
        d = v.created_at.strftime("%Y-%m-%d")
        per_day[d]["videos"] += 1
        per_day[d]["cost"] = round(per_day[d]["cost"] + v.cost_total, 4)
    upcoming = [video_dict(v) for v in db.query(Video).filter(Video.user_id == user.id, Video.publish_at > now, Video.status.in_(["ready", "published"])).order_by(Video.publish_at).limit(10)]
    errors = [video_dict(v) for v in db.query(Video).filter(Video.user_id == user.id, Video.status == "failed").order_by(Video.id.desc()).limit(5)]
    st = user_settings(user)
    return {
        "by_status": by_status, "per_day": per_day, "upcoming": upcoming, "recent_errors": errors,
        "spent_today": spent_since(db, user.id, today), "spent_month": spent_since(db, user.id, today.replace(day=1)),
        "daily_budget": st["daily_budget"], "monthly_budget": st["monthly_budget"], "paused": st.get("paused", False),
        "schedules_active": db.query(Schedule).filter(Schedule.user_id == user.id, Schedule.enabled.is_(True)).count(),
        "note": "Les vues/abonnés YouTube ne sont pas affichés : ils nécessitent la YouTube Analytics API (non incluse dans cette version).",
    }


@app.get("/api/notifications")
def notifications(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.query(Notification).filter(Notification.user_id == user.id).order_by(Notification.id.desc()).limit(30).all()
    return [{"id": n.id, "message": n.message, "read": n.read, "at": n.created_at.isoformat()} for n in rows]


@app.post("/api/notifications/read")
def read_notifications(user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.query(Notification).filter(Notification.user_id == user.id, Notification.read.is_(False)).update({"read": True})
    db.commit()
    return {"ok": True}


@app.post("/api/kill-switch")
def kill_switch(body: dict, user: User = Depends(current_user), db: Session = Depends(get_db)):
    on = bool(body.get("on", True))
    st = user_settings(user)
    st["paused"] = on
    user.settings = st
    if on:
        for v in db.query(Video).filter(Video.user_id == user.id, Video.status.in_(["queued", "running"])):
            v.cancel_requested = True
            if v.status == "queued":
                v.status = "cancelled"
    db.commit()
    return {"paused": on}
