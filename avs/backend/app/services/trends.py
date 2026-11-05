"""Signaux de tendance réels via YouTube Data API (chart=mostPopular). Sans clé : aucune donnée, donc aucune affirmation de tendance."""
import httpx

REGION = {"ar": "MA", "ary": "MA", "fr": "FR", "en": "US", "es": "ES"}


def trend_titles(api_key: str, language: str, max_results: int = 25) -> list[str]:
    if not api_key:
        return []
    try:
        r = httpx.get(
            "https://www.googleapis.com/youtube/v3/videos",
            params={
                "part": "snippet",
                "chart": "mostPopular",
                "regionCode": REGION.get(language, "US"),
                "maxResults": max_results,
                "key": api_key,
            },
            timeout=20,
        )
        r.raise_for_status()
        return [i["snippet"]["title"] for i in r.json().get("items", [])]
    except Exception:
        return []
