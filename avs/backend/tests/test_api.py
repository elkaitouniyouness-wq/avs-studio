"""Test d'intégration de l'API et du pipeline complet. Les services externes (Anthropic, Google TTS, Pexels, YouTube) sont
remplacés par des doubles ; FFmpeg, la base de données, les étapes, le QC, le budget et l'arrêt d'urgence sont réels."""
import os
import subprocess
import tempfile
import time

import pytest

TMP = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite:///{TMP}/t.db", MEDIA_DIR=f"{TMP}/media", COOKIE_SECURE="false", INLINE_JOBS="true",
                  ADMIN_EMAIL="a@b.c", ADMIN_PASSWORD="Str0ng-pass!", APP_SECRET_KEY="x" * 40)

from fastapi.testclient import TestClient  # noqa: E402

from app import main  # noqa: E402
from app.services import llm, media, tts, youtube  # noqa: E402


def sine_mp3(seconds=2.0):
    out = f"{TMP}/s.mp3"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"sine=f=300:d={seconds}", out], check=True)
    return open(out, "rb").read()


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(llm, "gen_script", lambda *a, **k: ({"title": "Titre", "scenes": [
        {"narration": "Première scène du test.", "visual_query": "ocean", "visual_description": "mer"},
        {"narration": "Deuxième scène du test.", "visual_query": "forest", "visual_description": "forêt"}], "claims": []}, 1000, 800))
    monkeypatch.setattr(llm, "gen_seo", lambda *a, **k: ({"titles": ["Un titre"], "description": "Desc", "tags": ["a", "b"], "hashtags": ["x"], "thumbnail_text": "Wow", "file_name": "un-titre", "category": "facts"}, 500, 300))
    monkeypatch.setattr(tts, "synthesize", lambda keys, text, voice: (sine_mp3(), "google-chirp"))
    monkeypatch.setattr(media, "fetch_for_scene", lambda *a, **k: None)  # -> cartes de remplacement (avertissement QC)
    with TestClient(main.app) as c:
        assert c.post("/api/auth/login", json={"email": "a@b.c", "password": "Str0ng-pass!"}).status_code == 200
        yield c


def wait(c, vid, final=("ready", "failed", "cancelled", "published"), timeout=120):
    t = time.time()
    while time.time() - t < timeout:
        v = c.get(f"/api/videos/{vid}").json()
        if v["status"] in final:
            return v
        time.sleep(0.5)
    raise AssertionError("timeout")


def test_auth_required_and_bad_login():
    with TestClient(main.app) as c:
        assert c.get("/api/videos").status_code == 401
        assert c.post("/api/auth/login", json={"email": "a@b.c", "password": "nope"}).status_code == 401


def test_full_pipeline_produces_real_video(client):
    r = client.post("/api/videos", json={"niche": "test", "topic": "Sujet unique A", "params": {"duration": 15, "format": "9:16", "resolution": "720p"}})
    assert r.status_code == 200
    v = wait(client, r.json()["id"])
    assert v["status"] == "ready", v["error"]
    assert v["qc"]["ok"] and v["has_video"] and v["has_thumb"]
    assert v["cost_total"] > 0
    f = client.get(f"/api/videos/{v['id']}/file")
    assert f.status_code == 200 and f.headers["content-type"] == "video/mp4" and len(f.content) > 1000
    assert client.get(f"/api/videos/{v['id']}/thumb").status_code == 200
    assert "-->" in client.get(f"/api/videos/{v['id']}/srt").text
    assert any("carte de remplacement" in w for w in v["qc"]["warnings"])  # honnêteté : média absent signalé


def test_manual_publish_requires_channel_and_never_auto_without_validation(client):
    r = client.post("/api/videos", json={"topic": "Sujet unique B", "params": {"duration": 15, "resolution": "720p"}, "auto_publish": True})
    v = wait(client, r.json()["id"])
    assert v["status"] == "ready"  # mode manuel par défaut : jamais publiée toute seule
    assert client.post(f"/api/videos/{v['id']}/publish", json={}).status_code == 422  # aucune chaîne


def test_budget_stops_production(client):
    client.put("/api/settings", json={"max_budget_per_video": 0.0001})
    r = client.post("/api/videos", json={"topic": "Sujet unique C", "params": {"duration": 15}})
    v = wait(client, r.json()["id"])
    client.put("/api/settings", json={"max_budget_per_video": 1.0})
    assert v["status"] == "failed" and "Budget" in v["error"]


def test_kill_switch_blocks_new_videos(client):
    assert client.post("/api/kill-switch", json={"on": True}).json()["paused"] is True
    assert client.post("/api/videos", json={"topic": "X"}).status_code == 423
    client.post("/api/kill-switch", json={"on": False})


def test_keys_are_never_returned(client):
    client.put("/api/keys", json={"pexels": "secret-value"})
    out = client.get("/api/keys").json()
    assert out["pexels"] == "user" and "secret-value" not in str(out)
    client.put("/api/keys", json={"pexels": ""})


def test_invalid_params_rejected(client):
    assert client.post("/api/videos", json={"params": {"duration": 99999}}).status_code == 422
    assert client.post("/api/videos", json={"params": {"format": "4:3"}}).status_code == 422


def test_youtube_resumable_offset_parser():
    class R:
        headers = {"Range": "bytes=0-1048575"}

    assert youtube._offset_from(R) == 1048576
    R.headers = {}
    assert youtube._offset_from(R) == 0
