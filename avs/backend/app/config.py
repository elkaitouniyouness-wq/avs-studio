from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_secret_key: str = "dev-secret-change-me"
    app_encryption_key: str = ""
    admin_email: str = ""
    admin_password: str = ""
    public_base_url: str = "http://localhost:3000"
    frontend_origin: str = "http://localhost:3000"
    cookie_secure: bool = True
    inline_jobs: bool = False

    database_url: str = "sqlite:///./avs.db"
    redis_url: str = "redis://localhost:6379/0"
    media_dir: str = "./media"

    anthropic_api_key: str = ""
    script_model: str = "claude-sonnet-5-5"
    google_tts_api_key: str = ""
    pexels_api_key: str = ""
    youtube_api_key: str = ""
    openai_api_key: str = ""
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.6-flash"          # texte (palier gratuit, vérifier ai.google.dev/pricing)
    gemini_fallback_models: str = "gemini-3.5-flash-lite,gemini-3.1-flash-lite,gemini-3.8-flash"  # essayés si le modèle principal a atteint son quota
    gemini_tts_model: str = "gemini-3.8-flash-tts"  # voix (palier gratuit, vérifier ai.google.dev/pricing)

    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""
    google_oauth_redirect_uri: str = "http://localhost:3000/api/youtube/callback"

    default_max_budget_per_video: float = 1.0
    default_daily_budget: float = 5.0

    # Tarifs ESTIMÉS (USD). À vérifier et ajuster selon la grille tarifaire en vigueur.
    price_llm_in_per_mtok: float = 3.0
    price_llm_out_per_mtok: float = 15.0
    price_tts_chirp_per_mchar: float = 30.0
    price_tts_standard_per_mchar: float = 16.0
    price_openai_tts_per_mchar: float = 15.0
    # Gemini : 0 = palier gratuit. Si la facturation est activée sur votre projet Google, mettez les tarifs réels.
    price_gemini_in_per_mtok: float = 0.0
    price_gemini_out_per_mtok: float = 0.0
    price_gemini_tts_per_mchar: float = 0.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
