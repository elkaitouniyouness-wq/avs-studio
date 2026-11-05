from .config import get_settings
from .security import decrypt_json

KEY_NAMES = ["anthropic", "google_tts", "pexels", "openai", "youtube_api", "gemini"]


def env_keys() -> dict:
    s = get_settings()
    return {
        "anthropic": s.anthropic_api_key,
        "google_tts": s.google_tts_api_key,
        "pexels": s.pexels_api_key,
        "openai": s.openai_api_key,
        "gemini": s.gemini_api_key,
        "youtube_api": s.youtube_api_key,
    }


def resolve_keys(user) -> dict:
    """Clés enregistrées par l'utilisateur (chiffrées en base) prioritaires sur le .env."""
    keys = env_keys()
    stored = decrypt_json(user.api_keys_enc) if user else {}
    for k in KEY_NAMES:
        if stored.get(k):
            keys[k] = stored[k]
    return keys
