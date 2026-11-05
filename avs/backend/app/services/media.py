"""Médias libres de droits via Pexels (licence Pexels). Repli : carte texte générée (signalée au contrôle qualité)."""
from pathlib import Path

import httpx
from PIL import Image, ImageDraw

ORIENT = {"9:16": "portrait", "16:9": "landscape", "1:1": "square"}


def _headers(key):
    return {"Authorization": key}


def search_video(key: str, query: str, fmt: str, min_dur: float, used: set, target_w: int) -> dict | None:
    r = httpx.get(
        "https://api.pexels.com/videos/search",
        headers=_headers(key),
        params={"query": query, "orientation": ORIENT.get(fmt, "landscape"), "per_page": 15},
        timeout=30,
    )
    if r.status_code != 200:
        return None
    for v in r.json().get("videos", []):
        if f"v{v['id']}" in used or v.get("duration", 0) < min(min_dur, 4):
            continue
        files = [f for f in v.get("video_files", []) if f.get("file_type") == "video/mp4" and f.get("width")]
        if not files:
            continue
        files.sort(key=lambda f: (abs(f["width"] - target_w), f["width"]))
        best = files[0]
        return {"kind": "video", "id": f"v{v['id']}", "url": best["link"], "credit": v.get("user", {}).get("name", ""), "page": v.get("url", "")}
    return None


def search_photo(key: str, query: str, fmt: str, used: set) -> dict | None:
    r = httpx.get(
        "https://api.pexels.com/v1/search",
        headers=_headers(key),
        params={"query": query, "orientation": ORIENT.get(fmt, "landscape"), "per_page": 15},
        timeout=30,
    )
    if r.status_code != 200:
        return None
    for p in r.json().get("photos", []):
        if f"p{p['id']}" in used:
            continue
        return {"kind": "image", "id": f"p{p['id']}", "url": p["src"].get("large2x") or p["src"]["original"], "credit": p.get("photographer", ""), "page": p.get("url", "")}
    return None


def download(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with httpx.stream("GET", url, timeout=120, follow_redirects=True) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_bytes(1 << 16):
                f.write(chunk)
    return dest


def fetch_for_scene(key: str, scene: dict, fmt: str, need_dur: float, used: set, target_w: int, workdir: Path, idx: int):
    """Retourne dict média ({kind,id,path,credit}) ou None si rien trouvé."""
    queries = [scene.get("visual_query", ""), " ".join(scene.get("visual_query", "").split()[:2])]
    for q in [q for q in queries if q]:
        for finder in (
            lambda: search_video(key, q, fmt, need_dur, used, target_w),
            lambda: search_photo(key, q, fmt, used),
        ):
            m = finder()
            if m:
                ext = ".mp4" if m["kind"] == "video" else ".jpg"
                m["path"] = str(download(m["url"], workdir / f"media_{idx:02d}{ext}"))
                return m
    return None


def make_card(text: str, size: tuple[int, int], dest: Path, idx: int) -> Path:
    """Carte de remplacement (dégradé + texte). Ce n'est PAS un média pertinent : le QC l'avertit."""
    w, h = size
    img = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(img)
    base = [(24, 32, 64), (64, 24, 48), (20, 56, 56), (56, 44, 20)][idx % 4]
    for y in range(h):
        k = y / h
        d.line([(0, y), (w, y)], fill=tuple(int(c * (1 + 0.8 * k)) for c in base))
    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest, quality=90)
    return dest
