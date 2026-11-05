"""Pipeline de production d'une vidéo. Chaque étape est idempotente : une reprise ne refait pas ce qui existe déjà.
Étapes : script -> voice -> media -> render -> seo -> thumbnail -> qc -> publish."""
import copy
import hashlib
import re
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import func

from . import options as O
from .config import get_settings
from .costs import add_cost, llm_cost, tts_cost
from .db import SessionLocal
from .keys import resolve_keys
from .models import Channel, JobLog, Notification, User, Video
from .security import decrypt
from .services import llm, media, render, thumb, trends, tts, youtube


class Cancelled(Exception):
    pass


class BudgetExceeded(Exception):
    pass


class StageError(Exception):
    """Erreur non réessayable (configuration, budget, etc.)."""


# ---------- utilitaires ----------
def workdir(video) -> Path:
    d = Path(get_settings().media_dir) / "videos" / str(video.id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def log(db, video, stage, msg, level="info"):
    db.add(JobLog(video_id=video.id, stage=stage, level=level, message=str(msg)[:4000]))
    db.commit()


def notify(db, user_id, msg):
    db.add(Notification(user_id=user_id, message=msg))
    db.commit()


def fingerprint(topic: str, lang: str) -> str:
    norm = re.sub(r"\W+", " ", topic.lower()).strip()
    return hashlib.sha256(f"{lang}|{norm}".encode()).hexdigest() if norm else ""


def user_settings(user) -> dict:
    return {**O.DEFAULT_SETTINGS, **(user.settings or {})}


def spent_since(db, user_id, since: datetime) -> float:
    return float(db.query(func.coalesce(func.sum(Video.cost_total), 0.0)).filter(Video.user_id == user_id, Video.created_at >= since).scalar() or 0.0)


def check_budget(db, video, user, upcoming: float = 0.0):
    st = user_settings(user)
    if video.cost_total + upcoming > float(st["max_budget_per_video"]):
        raise BudgetExceeded(f"Budget maximal par vidéo atteint ({video.cost_total:.3f} $ / {st['max_budget_per_video']} $)")
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    if spent_since(db, user.id, today) + upcoming > float(st["daily_budget"]):
        raise BudgetExceeded(f"Budget journalier atteint ({st['daily_budget']} $)")
    if spent_since(db, user.id, today.replace(day=1)) + upcoming > float(st["monthly_budget"]):
        raise BudgetExceeded(f"Budget mensuel atteint ({st['monthly_budget']} $)")


def check_cancel(db, video, user):
    db.refresh(video)
    db.refresh(user)
    if video.cancel_requested:
        raise Cancelled("Arrêt demandé")
    if user_settings(user).get("paused"):
        raise Cancelled("Automatisations en pause (arrêt d'urgence)")


def P(video) -> dict:
    return {**O.DEFAULT_PARAMS, **(video.params or {})}


# ---------- étapes ----------
def stage_script(db, video, user, keys):
    p = P(video)
    if video.script and video.scenes:
        return
    st = user_settings(user)
    lkey, model = llm.pick_llm(keys, get_settings().script_model)
    check_budget(db, video, user, 0.02)
    if not video.topic.strip():
        recent = [t for (t,) in db.query(Video.topic).filter(Video.user_id == user.id, Video.topic != "").order_by(Video.id.desc()).limit(40)]
        signals = trends.trend_titles(keys.get("youtube_api", ""), p["language"])
        ideas, i, o = llm.gen_ideas(lkey, model, video.niche or "culture générale", p.get("category"), p["language"], 5, recent, signals)
        add_cost(video, "ideas", llm_cost(i, o, model))
        pick = next((x for x in ideas if x.get("topic") and x["topic"] not in recent), None)
        if not pick:
            raise StageError("Aucune idée nouvelle trouvée")
        video.topic = pick["topic"]
        video.params = {**p, "trend_verified": bool(signals and pick.get("based_on_trend_signal"))}
        log(db, video, "script", f"Sujet choisi: {video.topic} (tendance vérifiée: {video.params['trend_verified']})")
        db.commit()
    data, i, o = llm.gen_script(lkey, model, video.topic, video.niche, p)
    add_cost(video, "script", llm_cost(i, o, model))
    if st.get("script_review", True) and int(p["duration"]) >= 90:
        check_budget(db, video, user, 0.02)
        data, i, o = llm.review_script(lkey, model, data, p)
        add_cost(video, "script_review", llm_cost(i, o, model))
    video.scenes = [{"i": n, "narration": s["narration"].strip(), "visual_query": s.get("visual_query", ""), "visual_description": s.get("visual_description", "")} for n, s in enumerate(data["scenes"])]
    video.script = "\n\n".join(s["narration"] for s in video.scenes)
    video.claims = data.get("claims", [])
    video.seo = {**(video.seo or {}), "working_title": data["title"]}
    video.fingerprint = fingerprint(video.topic, p["language"])
    db.commit()


def stage_voice(db, video, user, keys):
    """Une SEULE voix pour toute la vidéo : si un fournisseur échoue en cours de route, on refait toutes les scènes avec le suivant."""
    p = P(video)
    voice = O.resolve_voice(p["language"], p["voice_gender"], p["voice_style"], p["voice_speed"])
    wd = workdir(video)
    scenes = [dict(s) for s in video.scenes]
    chain = tts.provider_chain(keys)
    if not chain:
        raise StageError("Aucun fournisseur vocal configuré (ajoutez une clé Gemini gratuite, Google TTS ou OpenAI, ou activez EDGE_TTS)")
    # fournisseur déjà utilisé par les scènes existantes (reprise) : on le garde en premier pour rester cohérent
    done = [s.get("audio_provider") for s in scenes if s.get("audio_provider")]
    if done and done[0] in chain:
        chain = [done[0]] + [c for c in chain if c != done[0]]
    errors = []
    for prov in chain:
        try:
            for s in scenes:
                f = wd / f"audio_{s['i']:02d}.mp3"
                tag = voice["name"] + str(voice["rate"])
                if f.exists() and s.get("audio_text") == s["narration"] and s.get("audio_voice") == tag and s.get("audio_provider") == prov:
                    continue
                check_budget(db, video, user, tts_cost(len(s["narration"]), prov))
                mp3 = tts.synthesize_with(prov, keys, s["narration"], voice)
                f.write_bytes(mp3)
                render.trim_silence(str(f))
                add_cost(video, "audio", tts_cost(len(s["narration"]), prov))
                s.update(audio=f.name, audio_text=s["narration"], audio_voice=tag, audio_provider=prov, dur_audio=render.probe(str(f))["duration"])
                video.scenes = copy.deepcopy(scenes)
                db.commit()
            break
        except (Cancelled, BudgetExceeded, StageError):
            raise
        except Exception as e:  # noqa: BLE001
            errors.append(f"{prov}: {e}")
            log(db, video, "voice", f"Voix « {prov} » indisponible ({str(e)[:160]}) : on refait TOUTES les scènes avec la voix suivante pour garder la même voix.", "warn")
    else:
        raise StageError("Voix : tous les fournisseurs ont échoué — " + " | ".join(errors))
    video.scenes = copy.deepcopy(scenes)
    db.commit()


def stage_media(db, video, user, keys):
    p = P(video)
    size = O.video_size(p["format"], p["resolution"], p.get("draft", False))
    wd = workdir(video)
    scenes = [dict(s) for s in video.scenes]
    used = {s["media"]["id"] for s in scenes if s.get("media") and s["media"].get("id")}
    for s in scenes:
        m = s.get("media")
        if m and Path(m.get("path", "")).exists() and (m.get("locked") or m.get("query") == s["visual_query"]):
            continue
        found = None
        if keys.get("pexels") and s["visual_query"]:
            try:
                found = media.fetch_for_scene(keys["pexels"], s, p["format"], s.get("dur_audio", 5), used, size[0], wd, s["i"])
            except Exception as e:  # noqa: BLE001
                log(db, video, "media", f"Pexels scène {s['i']}: {e}", "warn")
        if found:
            found["query"] = s["visual_query"]
            used.add(found["id"])
            s["media"] = found
        else:
            card = media.make_card(s["narration"], size, wd / f"media_{s['i']:02d}.jpg", s["i"])
            s["media"] = {"kind": "image", "id": f"card{s['i']}", "path": str(card), "credit": "", "card": True, "query": s["visual_query"]}
            log(db, video, "media", f"Aucun média trouvé pour la scène {s['i']} : carte de remplacement", "warn")
        video.scenes = copy.deepcopy(scenes)
        db.commit()
    video.scenes = copy.deepcopy(scenes)
    db.commit()


def pick_music(video) -> str | None:
    d = Path(get_settings().media_dir) / "music"
    files = sorted([f for f in d.glob("*") if f.suffix.lower() in (".mp3", ".m4a", ".wav", ".ogg")]) if d.exists() else []
    return str(files[video.id % len(files)]) if files else None


def stage_render(db, video, user, keys):
    p = P(video)
    size = O.video_size(p["format"], p["resolution"], p.get("draft", False))
    wd = workdir(video)
    scenes = [dict(s) for s in video.scenes]
    segs, t = [], 0.0
    for s in scenes:
        out = wd / f"seg_{s['i']:02d}.mp4"
        dur = render.make_segment(s["media"]["kind"], s["media"]["path"], str(wd / s["audio"]), s["dur_audio"], size, str(out))
        s["start"], s["dur"] = round(t, 3), dur
        t += dur
        segs.append(str(out))
        check_cancel(db, video, user)
    concat = wd / "concat.mp4"
    render.concat_segments(segs, str(concat), str(wd))
    use_subs = bool(p.get("subtitles", True))  # (« subtitles » n'est pas une étape du pipeline : seule l'option compte)
    ass = None
    cues = render.build_cues([{"narration": s["narration"], "start": s["start"], "dur": s["dur"]} for s in scenes], 4 if size[1] > size[0] else 7)
    render.write_subtitles(cues, size, p["language"], str(wd / "subs.ass"), str(wd / "subs.srt"))
    if use_subs:
        ass = "subs.ass"
    music = pick_music(video) if p.get("music", True) else None
    final = wd / "final.mp4"
    render.finalize(str(concat), str(final), str(wd), ass, music, t, p.get("draft", False))
    info = render.probe(str(final))
    video.scenes = copy.deepcopy(scenes)
    video.video_path = str(final)
    video.duration_actual = info["duration"]
    video.qc = {**(video.qc or {}), "music_used": bool(music)}
    for f in segs + [str(concat)]:
        Path(f).unlink(missing_ok=True)
    db.commit()


def stage_seo(db, video, user, keys):
    p = P(video)
    if video.seo.get("titles"):
        return
    check_budget(db, video, user, 0.01)
    is_short = p["format"] != "16:9" and int(p["duration"]) <= 180
    lkey, model = llm.pick_llm(keys, get_settings().script_model)
    raw, i, o = llm.gen_seo(lkey, model, video.script, video.seo.get("working_title", video.topic), p)
    add_cost(video, "seo", llm_cost(i, o, model))
    video.seo = llm.sanitize_seo(raw, video.seo.get("working_title", video.topic), is_short)
    db.commit()


def stage_thumbnail(db, video, user, keys):
    p = P(video)
    if not video.video_path or not Path(video.video_path).exists():
        raise StageError("Vidéo finale introuvable pour la miniature")
    wd = workdir(video)
    fr = wd / "frame.jpg"
    render.extract_frame(video.video_path, str(fr), min(1.0, (video.duration_actual or 2) / 2))
    out = wd / "thumbnail.jpg"
    thumb.make_thumbnail(str(fr), video.seo.get("thumbnail_text") or video.seo.get("title") or video.topic, p["language"], str(out))
    video.thumb_path = str(out)
    db.commit()


def stage_qc(db, video, user, keys):
    p = P(video)
    st = user_settings(user)
    errors, warnings = [], []
    path = Path(video.video_path or "")
    if not path.exists():
        errors.append("Vidéo finale absente")
    else:
        info = render.probe(str(path))
        if not info["has_video"] or not info["has_audio"]:
            errors.append("Piste vidéo ou audio manquante")
        size = O.video_size(p["format"], p["resolution"], p.get("draft", False))
        if (info["width"], info["height"]) != size:
            errors.append(f"Format inattendu {info['width']}x{info['height']} (attendu {size[0]}x{size[1]})")
        vol = render.mean_volume_db(str(path))
        if vol is None or vol < -40:
            errors.append(f"Son quasi silencieux (volume moyen {vol} dB)")
        elif vol > -8:
            warnings.append(f"Son très fort ({vol} dB)")
        req = int(p["duration"])
        if info["duration"] > req * 1.4 or info["duration"] < req * 0.6:
            warnings.append(f"Durée réelle {info['duration']:.0f}s éloignée de la durée demandée ({req}s)")
        if p["format"] != "16:9" and info["duration"] > 180:
            warnings.append("Plus de 3 minutes : ne sera pas classée comme Short par YouTube")
        # synchronisation : somme des segments ≈ durée finale
        if video.scenes and abs(sum(s.get("dur", 0) for s in video.scenes) - info["duration"]) > 0.6:
            errors.append("Désynchronisation audio/vidéo détectée")
        if info["duration"] < 3:
            errors.append("Vidéo trop courte")
    if "seo" in (video.steps or []) or video.seo.get("title"):
        t, d, tags = video.seo.get("title", ""), video.seo.get("description", ""), video.seo.get("tags", [])
        if not t or len(t) > 100:
            errors.append("Titre manquant ou > 100 caractères")
        if not d or len(d) > 5000:
            errors.append("Description manquante ou > 5000 caractères")
        if sum(len(x) + 1 for x in tags) > 500:
            errors.append("Tags > 500 caractères")
    else:
        errors.append("Métadonnées SEO manquantes")
    missing = [s["i"] for s in video.scenes if not Path(s.get("media", {}).get("path", "")).exists() and not Path(video.video_path or "").exists()]
    if missing:
        errors.append(f"Médias indisponibles (scènes {missing})")
    cards = [s["i"] for s in video.scenes if s.get("media", {}).get("card")]
    if cards:
        warnings.append(f"{len(cards)} scène(s) avec carte de remplacement (aucun média trouvé)")
    custom = [s["i"] for s in video.scenes if s.get("media", {}).get("locked")]
    if custom:
        warnings.append("Médias ajoutés manuellement : vérifiez que vous en détenez les droits")
    if p.get("music") and video.qc.get("music_used"):
        warnings.append("Musique de fond personnelle : vérifiez sa licence pour YouTube")
    dup = None
    if video.fingerprint:
        dup = db.query(Video).filter(Video.user_id == user.id, Video.fingerprint == video.fingerprint, Video.id != video.id, Video.status.in_(["ready", "publishing", "published"])).first()
    if dup:
        warnings.append(f"Doublon potentiel de la vidéo #{dup.id}")
    needs_review = bool(video.claims) and bool(st.get("auto_block_on_claims", True))
    if needs_review:
        warnings.append(f"{len(video.claims)} affirmation(s) factuelle(s) à vérifier avant publication")
    video.qc = {**video.qc, "errors": errors, "warnings": warnings, "duplicate": bool(dup), "needs_review": needs_review, "ok": not errors, "checked_at": datetime.utcnow().isoformat()}
    db.commit()


def publish_video(db, video, user):
    """Envoi sur YouTube. Idempotent : ne publie jamais deux fois, reprend un upload interrompu."""
    if video.youtube_video_id:
        video.status = "published"
        db.commit()
        return
    if not video.qc.get("ok"):
        raise StageError("Contrôle qualité non réussi : publication refusée")
    ch = db.get(Channel, video.channel_id) if video.channel_id else None
    if not ch or ch.user_id != user.id:
        raise StageError("Aucune chaîne YouTube sélectionnée")
    dup = db.query(Video).filter(Video.channel_id == ch.id, Video.fingerprint == video.fingerprint, Video.fingerprint != "", Video.youtube_video_id.isnot(None), Video.id != video.id).first()
    if dup:
        raise StageError(f"Doublon : la vidéo #{dup.id} avec le même sujet est déjà publiée sur cette chaîne")
    token = youtube.access_token(decrypt(ch.refresh_token_enc))
    p = P(video)
    st = user_settings(user)
    cat = O.CATEGORY_TO_YT.get(video.seo.get("category") or p.get("category"), "27")
    meta = youtube.build_metadata(video.seo, p["language"], video.privacy, video.publish_at, cat, bool(st.get("declare_ai_content", False)))
    video.status = "publishing"
    db.commit()
    size = Path(video.video_path).stat().st_size
    if not video.upload_url:
        video.upload_url = youtube.init_session(token, meta, size)
        db.commit()
    res = youtube.upload_file(token, video.upload_url, video.video_path)
    video.youtube_video_id = res["id"]
    video.status = "published"
    video.upload_url = None
    db.commit()
    log(db, video, "publish", f"Publié sur YouTube: {res['id']} ({video.privacy})")
    if video.thumb_path and Path(video.thumb_path).exists():
        try:
            youtube.set_thumbnail(token, res["id"], video.thumb_path)
        except Exception as e:  # noqa: BLE001
            log(db, video, "publish", str(e), "warn")
    notify(db, user.id, f"Vidéo publiée : {video.seo.get('title', video.topic)}")


def stage_publish(db, video, user, keys):
    st = user_settings(user)
    auto_ok = video.auto_publish and st.get("publish_mode") == "auto" and video.qc.get("ok") and not video.qc.get("needs_review") and not video.qc.get("duplicate") and video.channel_id
    if not auto_ok:
        log(db, video, "publish", "Validation manuelle requise avant publication")
        return
    publish_video(db, video, user)


STAGES = {"script": stage_script, "voice": stage_voice, "media": stage_media, "render": stage_render, "seo": stage_seo, "thumbnail": stage_thumbnail, "qc": stage_qc, "publish": stage_publish}


def active_stages(video) -> list[str]:
    enabled = set(video.steps or O.DEFAULT_STEPS) | set(O.REQUIRED_STEPS) | {"qc"}
    return [s for s in O.STEP_ORDER if s in enabled]


# ---------- points d'entrée des jobs (RQ) ----------
def run_video(video_id: int):
    db = SessionLocal()
    try:
        video = db.get(Video, video_id)
        if not video or video.status in ("cancelled", "published"):
            return
        user = db.get(User, video.user_id)
        keys = resolve_keys(user)
        retry = (video.params or {}).get("on_error", "retry") == "retry"
        stages = active_stages(video)
        video.status, video.error, video.cancel_requested = "running", None, False
        db.commit()
        try:
            for n, stage in enumerate(stages):
                check_cancel(db, video, user)
                video.stage, video.progress = stage, int(100 * n / len(stages))
                db.commit()
                attempts = 3 if retry else 1
                for a in range(attempts):
                    try:
                        STAGES[stage](db, video, user, keys)
                        break
                    except (Cancelled, BudgetExceeded, StageError):
                        raise
                    except Exception as e:  # noqa: BLE001
                        video.retries += 1
                        log(db, video, stage, f"Tentative {a + 1}/{attempts} échouée: {e}\n{traceback.format_exc()[-1200:]}", "error")
                        if a == attempts - 1:
                            raise
                        time.sleep(2 * (a + 1))
            video.status, video.stage, video.progress = "ready", "done", 100
            if video.qc.get("ok") is False:
                video.status, video.error = "failed", "Contrôle qualité échoué : " + "; ".join(video.qc.get("errors", []))
            if video.status == "ready":
                notify(db, user.id, f"Vidéo prête à valider : {video.seo.get('title', video.topic)}")
            if "publish" in stages and video.youtube_video_id:
                video.status = "published"
            db.commit()
        except Cancelled as e:
            video.status, video.error = "cancelled", str(e)
            db.commit()
            log(db, video, video.stage, f"Annulée: {e}", "warn")
        except (BudgetExceeded, StageError) as e:
            video.status, video.error = "failed", str(e)
            db.commit()
            log(db, video, video.stage, str(e), "error")
            notify(db, user.id, f"Échec vidéo #{video.id} : {e}")
        except Exception as e:  # noqa: BLE001
            video.status, video.error = "failed", str(e)[:1000]
            db.commit()
            notify(db, user.id, f"Échec vidéo #{video.id} : {str(e)[:200]}")
    finally:
        db.close()


def run_publish(video_id: int):
    """Publication manuelle validée par l'utilisateur (ou reprise d'un upload interrompu)."""
    db = SessionLocal()
    try:
        video = db.get(Video, video_id)
        user = db.get(User, video.user_id)
        if user_settings(user).get("paused"):
            video.status, video.error = "ready", "Automatisations en pause"
            db.commit()
            return
        try:
            video.stage, video.error = "publish", None
            db.commit()
            publish_video(db, video, user)
        except Exception as e:  # noqa: BLE001
            video.status = "ready" if not video.upload_url else "failed"  # upload_url conservé = reprise possible
            video.error = str(e)[:1000]
            db.commit()
            log(db, video, "publish", str(e), "error")
            notify(db, user.id, f"Publication échouée (vidéo #{video.id}) : {str(e)[:200]}")
    finally:
        db.close()
