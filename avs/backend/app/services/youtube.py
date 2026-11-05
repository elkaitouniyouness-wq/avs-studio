"""Publication YouTube : OAuth 2.0 officiel + téléversement résumable (YouTube Data API v3).
Quota par défaut : 10 000 unités/jour, un videos.insert coûte 1 600 unités (~6 envois/jour)."""
import os
from datetime import timezone
from urllib.parse import urlencode

import httpx

from ..config import get_settings

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/youtube/v3"
UPLOAD = "https://www.googleapis.com/upload/youtube/v3"
SCOPES = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly"
CHUNK = 8 * 1024 * 1024  # multiple de 256 Kio, obligatoire pour l'upload résumable


class YouTubeError(Exception):
    pass


def configured() -> bool:
    s = get_settings()
    return bool(s.google_oauth_client_id and s.google_oauth_client_secret)


def auth_url(state: str) -> str:
    s = get_settings()
    if not configured():
        raise YouTubeError("OAuth Google non configuré (GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET)")
    q = {
        "client_id": s.google_oauth_client_id,
        "redirect_uri": s.google_oauth_redirect_uri,
        "response_type": "code",
        "scope": SCOPES,
        "access_type": "offline",
        "prompt": "consent select_account",
        "include_granted_scopes": "true",
        "state": state,
    }
    return f"{AUTH_URL}?{urlencode(q)}"


def exchange_code(code: str) -> dict:
    s = get_settings()
    r = httpx.post(
        TOKEN_URL,
        data={"code": code, "client_id": s.google_oauth_client_id, "client_secret": s.google_oauth_client_secret, "redirect_uri": s.google_oauth_redirect_uri, "grant_type": "authorization_code"},
        timeout=30,
    )
    if r.status_code != 200:
        raise YouTubeError(f"Échange du code OAuth refusé: {r.text[:200]}")
    return r.json()


def access_token(refresh_token: str) -> str:
    s = get_settings()
    r = httpx.post(
        TOKEN_URL,
        data={"refresh_token": refresh_token, "client_id": s.google_oauth_client_id, "client_secret": s.google_oauth_client_secret, "grant_type": "refresh_token"},
        timeout=30,
    )
    if r.status_code != 200:
        raise YouTubeError(f"Jeton YouTube expiré ou révoqué, reconnectez la chaîne: {r.text[:200]}")
    return r.json()["access_token"]


def my_channels(token: str) -> list[dict]:
    r = httpx.get(f"{API}/channels", params={"part": "snippet", "mine": "true"}, headers={"Authorization": f"Bearer {token}"}, timeout=30)
    if r.status_code != 200:
        raise YouTubeError(f"Lecture de la chaîne impossible: {r.text[:200]}")
    return [{"id": i["id"], "title": i["snippet"]["title"]} for i in r.json().get("items", [])]


def build_metadata(seo: dict, language: str, privacy: str, publish_at, category_id: str, declare_ai: bool) -> dict:
    status = {"privacyStatus": privacy, "selfDeclaredMadeForKids": False}
    if publish_at:
        # La programmation YouTube exige privacyStatus=private + publishAt (ISO 8601 UTC).
        status["privacyStatus"] = "private"
        status["publishAt"] = publish_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z") if publish_at.tzinfo else publish_at.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    if declare_ai:
        status["containsSyntheticMedia"] = True
    lang = {"ary": "ar"}.get(language, language)
    return {
        "snippet": {
            "title": seo["title"][:100],
            "description": seo["description"][:5000],
            "tags": seo.get("tags", []),
            "categoryId": category_id,
            "defaultLanguage": lang,
            "defaultAudioLanguage": lang,
        },
        "status": status,
    }


def init_session(token: str, meta: dict, size: int) -> str:
    r = httpx.post(
        f"{UPLOAD}/videos",
        params={"uploadType": "resumable", "part": "snippet,status"},
        headers={"Authorization": f"Bearer {token}", "X-Upload-Content-Length": str(size), "X-Upload-Content-Type": "video/mp4"},
        json=meta,
        timeout=60,
    )
    if r.status_code != 200:
        raise YouTubeError(f"Ouverture de la session d'upload refusée ({r.status_code}): {r.text[:300]}")
    return r.headers["Location"]


def _offset_from(resp: httpx.Response) -> int:
    rng = resp.headers.get("Range")  # "bytes=0-1234"
    return int(rng.split("-")[1]) + 1 if rng else 0


def upload_file(token: str, session_url: str, path: str, progress=None) -> dict:
    """Téléverse (ou reprend) le fichier. Retourne la ressource vidéo JSON."""
    total = os.path.getsize(path)
    h = {"Authorization": f"Bearer {token}"}
    probe = httpx.put(session_url, headers={**h, "Content-Range": f"bytes */{total}", "Content-Length": "0"}, timeout=60)
    if probe.status_code in (200, 201):
        return probe.json()
    offset = _offset_from(probe) if probe.status_code == 308 else 0
    with open(path, "rb") as f:
        while offset < total:
            f.seek(offset)
            data = f.read(CHUNK)
            end = offset + len(data) - 1
            r = None
            for attempt in range(4):
                try:
                    r = httpx.put(session_url, headers={**h, "Content-Range": f"bytes {offset}-{end}/{total}", "Content-Type": "video/mp4"}, content=data, timeout=300)
                    if r.status_code < 500:
                        break
                except httpx.HTTPError:
                    pass
            if r is None or r.status_code >= 500:
                raise YouTubeError("Serveur YouTube indisponible pendant l'upload (reprise possible)")
            if r.status_code in (200, 201):
                return r.json()
            if r.status_code == 308:
                offset = _offset_from(r)
                if progress:
                    progress(offset / total)
                continue
            raise YouTubeError(f"Upload refusé ({r.status_code}): {r.text[:300]}")
    raise YouTubeError("Upload terminé sans réponse de YouTube")


def set_thumbnail(token: str, video_id: str, path: str):
    with open(path, "rb") as f:
        r = httpx.post(
            f"{UPLOAD}/thumbnails/set",
            params={"videoId": video_id, "uploadType": "media"},
            headers={"Authorization": f"Bearer {token}", "Content-Type": "image/jpeg"},
            content=f.read(),
            timeout=60,
        )
    if r.status_code != 200:
        raise YouTubeError(f"Miniature non envoyée ({r.status_code}): la chaîne doit être vérifiée par téléphone. {r.text[:150]}")
