"""Estimation des coûts. Les tarifs sont des ESTIMATIONS configurables (voir config.py)."""
from .config import get_settings


def llm_cost(in_tok: int, out_tok: int, model: str = "") -> float:
    s = get_settings()
    if model.startswith("gemini"):
        return in_tok / 1e6 * s.price_gemini_in_per_mtok + out_tok / 1e6 * s.price_gemini_out_per_mtok
    return in_tok / 1e6 * s.price_llm_in_per_mtok + out_tok / 1e6 * s.price_llm_out_per_mtok


def tts_cost(chars: int, provider: str) -> float:
    s = get_settings()
    per_m = {
        "google-chirp": s.price_tts_chirp_per_mchar,
        "google-standard": s.price_tts_standard_per_mchar,
        "openai": s.price_openai_tts_per_mchar,
        "gemini": s.price_gemini_tts_per_mchar,
        "edge": 0.0,
    }.get(provider, s.price_tts_chirp_per_mchar)
    return chars / 1e6 * per_m


def add_cost(video, key: str, amount: float):
    c = dict(video.costs or {})
    c[key] = round(c.get(key, 0.0) + amount, 6)
    video.costs = c
    video.cost_total = round(sum(c.values()), 6)


def estimate(params: dict, review: bool = True) -> dict:
    """Estimation avant lancement (hypothèses : ~6 caractères par mot, tokens moyens observés)."""
    from .options import word_budget

    words = word_budget(int(params["duration"]), params["language"], params.get("voice_speed", 1.0))
    chars = words * 6
    script = llm_cost(2500, 1800 + words * 3) + (llm_cost(2500 + words * 3, 1800 + words * 3) if review and int(params["duration"]) >= 90 else 0)
    seo = llm_cost(1500 + words * 3, 900)
    audio = tts_cost(chars, "google-chirp")
    return {"script": round(script, 4), "audio": round(audio, 4), "seo": round(seo, 4), "images_video": 0.0, "render": 0.0, "total": round(script + audio + seo, 4)}
