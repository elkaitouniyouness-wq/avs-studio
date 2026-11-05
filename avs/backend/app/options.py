"""Options exposées à l'interface et règles de génération."""

DURATIONS = [8, 15, 30, 45, 60, 90, 180, 300, 600]
FORMATS = {"9:16": (9, 16), "16:9": (16, 9), "1:1": (1, 1)}
RESOLUTIONS = {"720p": 720, "1080p": 1080, "4k": 2160}
VIDEO_LANGS = {"ar": "العربية الفصحى", "ary": "الدارجة المغربية (Darija)", "fr": "Français", "en": "English", "es": "Español"}
STYLES = ["realistic", "cinematic", "documentary", "illustration", "animation", "stock", "custom"]
CATEGORIES = [
    "facts", "science", "history", "tech_ai", "general_culture", "mystery", "education", "storytelling", "news",
]
VOICE_STYLES = ["deep_pro", "natural", "energetic", "documentary", "calm"]

# Mots par minute (narration normale) selon la langue.
WPM = {"ar": 125, "ary": 130, "fr": 150, "en": 155, "es": 155}

DEFAULT_STEPS = ["script", "voice", "media", "render", "subtitles", "seo", "thumbnail", "qc"]
# Ordre fixe (chaque étape dépend de la précédente) : on peut activer/désactiver, pas réordonner.
STEP_ORDER = ["script", "voice", "media", "render", "seo", "thumbnail", "qc", "publish"]
REQUIRED_STEPS = ["script", "voice", "media", "render"]

DEFAULT_PARAMS = {
    "language": "fr",
    "duration": 60,
    "format": "9:16",
    "resolution": "1080p",
    "style": "stock",
    "voice_gender": "male",
    "voice_style": "natural",
    "voice_speed": 1.0,
    "subtitles": True,
    "music": True,
    "draft": False,
    "audience": "grand public",
    "category": "facts",
}

PRESETS = {
    "Shorts rapides": {"duration": 30, "format": "9:16", "voice_style": "energetic", "voice_speed": 1.05, "category": "facts"},
    "Documentaire professionnel": {"duration": 300, "format": "16:9", "voice_style": "documentary", "style": "documentary", "category": "history"},
    "Faits étonnants": {"duration": 45, "format": "9:16", "voice_style": "energetic", "category": "facts"},
    "Vidéo éducative": {"duration": 180, "format": "16:9", "voice_style": "natural", "category": "education"},
}

DEFAULT_SETTINGS = {
    "ui_lang": "fr",
    "theme": "dark",
    "timezone": "Africa/Casablanca",
    "expert_mode": False,
    "max_budget_per_video": 1.0,
    "daily_budget": 5.0,
    "monthly_budget": 100.0,
    "publish_mode": "manual",  # manual | auto
    "auto_block_on_claims": True,
    "script_review": True,
    "paused": False,
    "defaults": DEFAULT_PARAMS,
}

# Catégories YouTube (videoCategoryId).
YT_CATEGORY_IDS = {
    "film": "1", "autos": "2", "music": "10", "pets": "15", "sports": "17", "gaming": "20", "people": "22",
    "comedy": "23", "entertainment": "24", "news": "25", "howto": "26", "education": "27", "science": "28",
}
CATEGORY_TO_YT = {
    "facts": "27", "science": "28", "history": "27", "tech_ai": "28", "general_culture": "27",
    "mystery": "24", "education": "27", "storytelling": "24", "news": "25",
}

LANG_TTS = {"ar": "ar-XA", "ary": "ar-XA", "fr": "fr-FR", "en": "en-US", "es": "es-ES"}
CHIRP_MALE = {"deep_pro": "Charon", "natural": "Orus", "energetic": "Fenrir", "documentary": "Orus", "calm": "Charon"}
CHIRP_FEMALE = {"deep_pro": "Kore", "natural": "Aoede", "energetic": "Zephyr", "documentary": "Kore", "calm": "Leda"}
STYLE_RATE = {"energetic": 1.08, "calm": 0.92, "documentary": 0.98, "deep_pro": 0.97, "natural": 1.0}


def resolve_voice(lang: str, gender: str, style: str, speed: float = 1.0) -> dict:
    code = LANG_TTS.get(lang, "en-US")
    table = CHIRP_FEMALE if gender == "female" else CHIRP_MALE
    name = table.get(style, "Orus" if gender != "female" else "Aoede")
    rate = max(0.7, min(1.4, STYLE_RATE.get(style, 1.0) * float(speed or 1.0)))
    return {
        "language_code": code,
        "name": f"{code}-Chirp3-HD-{name}",
        "gender": "FEMALE" if gender == "female" else "MALE",
        "rate": round(rate, 3),
        "openai_voice": "nova" if gender == "female" else "onyx",
        "style": style,
    }


def video_size(fmt: str, resolution: str, draft: bool = False) -> tuple[int, int]:
    short = 480 if draft else RESOLUTIONS.get(resolution, 1080)
    a, b = FORMATS.get(fmt, (9, 16))
    if a == b:
        w, h = short, short
    elif a < b:
        w, h = short, short * b // a
    else:
        w, h = short * a // b, short
    return w - w % 2, h - h % 2


def scene_plan(duration: int, fmt: str) -> int:
    """Nombre de scènes cible selon la durée : plus court = montage plus rapide."""
    per = 4.0 if duration <= 60 else 6.0 if duration <= 180 else 8.0
    return max(2, round(duration / per))


def word_budget(duration: int, lang: str, speed: float = 1.0) -> int:
    return max(12, int(duration * WPM.get(lang, 150) / 60 * float(speed or 1.0) * 0.95))
