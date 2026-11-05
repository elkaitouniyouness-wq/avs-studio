"""Synthèse vocale réelle. Chaîne : Gemini TTS -> Google Cloud TTS -> OpenAI TTS (si clés) -> Edge TTS (gratuit, sans clé, non officiel)."""
import asyncio
import base64
import os
import re
import subprocess
import time

import httpx


class TTSError(Exception):
    pass


def _google(key: str, text: str, voice: dict, rate: float, named: bool) -> bytes:
    v = {"languageCode": voice["language_code"], "ssmlGender": voice["gender"]}
    if named:
        v["name"] = voice["name"]
    body = {"input": {"text": text}, "voice": v, "audioConfig": {"audioEncoding": "MP3", "speakingRate": rate, "sampleRateHertz": 44100}}
    r = httpx.post("https://texttospeech.googleapis.com/v1/text:synthesize", params={"key": key}, json=body, timeout=60)
    if r.status_code != 200:
        raise TTSError(f"Google TTS {r.status_code}: {r.text[:200]}")
    return base64.b64decode(r.json()["audioContent"])


def _openai(key: str, text: str, voice: dict, rate: float) -> bytes:
    r = httpx.post(
        "https://api.openai.com/v1/audio/speech",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": "gpt-4o-mini-tts", "voice": voice["openai_voice"], "input": text, "response_format": "mp3", "speed": max(0.25, min(4.0, rate))},
        timeout=90,
    )
    if r.status_code != 200:
        raise TTSError(f"OpenAI TTS {r.status_code}: {r.text[:200]}")
    return r.content


STYLE_PROMPT = {
    "energetic": "Read this in an energetic, upbeat, engaging tone",
    "calm": "Read this slowly, calmly and warmly, like telling a story",
    "documentary": "Read this in a deep, authoritative documentary narrator tone",
    "deep_pro": "Read this in a deep, professional and confident voice",
    "natural": "Read this naturally, like a friendly human speaking to a friend",
}


def pcm_to_mp3(pcm: bytes, rate: int = 24000) -> bytes:
    p = subprocess.run(["ffmpeg", "-v", "error", "-f", "s16le", "-ar", str(rate), "-ac", "1", "-i", "pipe:0", "-f", "mp3", "-b:a", "128k", "pipe:1"], input=pcm, capture_output=True)
    if p.returncode != 0 or not p.stdout:
        raise TTSError("Conversion audio Gemini échouée: " + p.stderr.decode(errors="ignore")[-200:])
    return p.stdout


_GEMINI_COOLDOWN_UNTIL = 0.0


def _gemini(key: str, text: str, voice: dict) -> bytes:
    from ..config import get_settings

    model = get_settings().gemini_tts_model
    pace = ", at a slightly faster pace" if voice["rate"] > 1.05 else ", at a slightly slower pace" if voice["rate"] < 0.95 else ""
    prompt = f"{STYLE_PROMPT.get(voice.get('style', 'natural'), STYLE_PROMPT['natural'])}{pace}: {text}"
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseModalities": ["AUDIO"], "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice["name"].split("-")[-1]}}}},
    }
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    global _GEMINI_COOLDOWN_UNTIL
    if time.time() < _GEMINI_COOLDOWN_UNTIL:
        raise TTSError("Gemini TTS en pause (quota atteint), voix suivante utilisée")
    r = None
    for attempt in range(3):
        r = httpx.post(url, headers={"x-goog-api-key": key}, json=body, timeout=180)
        if r.status_code in (429, 500, 503):
            if attempt < 2:
                time.sleep(8 * (attempt + 1))
            continue
        break
    if r is not None and r.status_code == 429:
        _GEMINI_COOLDOWN_UNTIL = time.time() + 300  # évite d'attendre à chaque scène
    if r is None or r.status_code != 200:
        raise TTSError(f"Gemini TTS {getattr(r, 'status_code', '?')}: {getattr(r, 'text', '')[:200]}")
    try:
        inline = r.json()["candidates"][0]["content"]["parts"][0]["inlineData"]
    except (KeyError, IndexError, TypeError):
        raise TTSError("Gemini TTS : pas d'audio dans la réponse (réessayez)")
    m = re.search(r"rate=(\d+)", inline.get("mimeType", ""))
    return pcm_to_mp3(base64.b64decode(inline["data"]), int(m.group(1)) if m else 24000)


EDGE_VOICES = {
    "ar-XA": {"MALE": "ar-MA-JamalNeural", "FEMALE": "ar-MA-MounaNeural"},
    "fr-FR": {"MALE": "fr-FR-HenriNeural", "FEMALE": "fr-FR-DeniseNeural"},
    "en-US": {"MALE": "en-US-GuyNeural", "FEMALE": "en-US-JennyNeural"},
    "es-ES": {"MALE": "es-ES-AlvaroNeural", "FEMALE": "es-ES-ElviraNeural"},
}


def _edge(text: str, voice: dict) -> bytes:
    """Voix Microsoft Edge (service non officiel, gratuit, sans clé). Peut cesser de fonctionner sans préavis."""
    try:
        import edge_tts
    except ImportError:
        raise TTSError("edge-tts non installé (reconstruire l'image api/worker)")
    name = EDGE_VOICES.get(voice["language_code"], EDGE_VOICES["en-US"])[voice["gender"]]
    pct = int(round((voice["rate"] - 1.0) * 100))
    rate = f"{pct:+d}%"

    async def run() -> bytes:
        out = b""
        async for chunk in edge_tts.Communicate(text, name, rate=rate).stream():
            if chunk["type"] == "audio":
                out += chunk["data"]
        return out

    data = asyncio.run(run())
    if not data:
        raise TTSError("Edge TTS : aucun audio reçu")
    return data


def provider_chain(keys: dict) -> list[str]:
    """Ordre de préférence des fournisseurs disponibles."""
    chain = []
    if keys.get("gemini"):
        chain.append("gemini")
    if keys.get("google_tts"):
        chain += ["google-chirp", "google-standard"]
    if keys.get("openai"):
        chain.append("openai")
    if os.environ.get("EDGE_TTS", "true").lower() not in ("0", "false", "no"):
        chain.append("edge")
    return chain


def synthesize_with(provider: str, keys: dict, text: str, voice: dict) -> bytes:
    """Synthèse avec UN fournisseur précis (pas de repli silencieux : la voix doit rester la même sur toute la vidéo)."""
    text = text.strip()
    if not text:
        raise TTSError("Texte vide")
    if provider == "gemini":
        return _gemini(keys["gemini"], text, voice)
    if provider == "google-chirp":
        return _google(keys["google_tts"], text, voice, voice["rate"], True)
    if provider == "google-standard":
        return _google(keys["google_tts"], text, voice, voice["rate"], False)
    if provider == "openai":
        return _openai(keys["openai"], text, voice, voice["rate"])
    if provider == "edge":
        return _edge(text, voice)
    raise TTSError(f"Fournisseur inconnu : {provider}")


def synthesize(keys: dict, text: str, voice: dict) -> tuple[bytes, str]:
    """Retourne (mp3, fournisseur). Lève TTSError si tous les fournisseurs échouent."""
    text = text.strip()
    if not text:
        raise TTSError("Texte vide")
    errors = []
    attempts = []
    if keys.get("gemini"):
        attempts.append(("gemini", lambda: _gemini(keys["gemini"], text, voice)))
    if keys.get("google_tts"):
        attempts += [
            ("google-chirp", lambda: _google(keys["google_tts"], text, voice, voice["rate"], True)),
            ("google-standard", lambda: _google(keys["google_tts"], text, voice, voice["rate"], False)),
        ]
    if keys.get("openai"):
        attempts.append(("openai", lambda: _openai(keys["openai"], text, voice, voice["rate"])))
    if os.environ.get("EDGE_TTS", "true").lower() not in ("0", "false", "no"):
        attempts.append(("edge", lambda: _edge(text, voice)))
    if not attempts:
        raise TTSError("Aucun fournisseur vocal configuré (ajoutez une clé Gemini gratuite, Google TTS ou OpenAI)")
    for name, fn in attempts:
        try:
            return fn(), name
        except Exception as e:  # noqa: BLE001 - on tente le fournisseur suivant
            errors.append(f"{name}: {e}")
    raise TTSError(" | ".join(errors))
