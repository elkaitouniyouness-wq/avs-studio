"""Génération de texte via Anthropic : idées, scripts, SEO. Retourne toujours (données, tokens_in, tokens_out)."""
import json
import re

from ..options import VIDEO_LANGS, scene_plan, word_budget


class LLMError(Exception):
    pass


def parse_json(text: str):
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.S)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    for o, c in (("{", "}"), ("[", "]")):
        i, j = t.find(o), t.rfind(c)
        if i != -1 and j > i:
            try:
                return json.loads(t[i : j + 1])
            except json.JSONDecodeError:
                continue
    raise LLMError("Réponse IA non exploitable (JSON invalide)")


_AR = re.compile(r"[\u0600-\u06FF]")


def fix_rtl(text: str) -> str:
    """Certains modèles renvoient parfois l'arabe en ordre visuel (texte à l'envers). Détection prudente puis retournement."""
    if not isinstance(text, str) or len(_AR.findall(text)) < 12:
        return text
    words = text.split()
    normal = sum(1 for w in words if w.startswith("ال") or w.startswith("و") and w[1:3] == "ال")
    reversed_ = sum(1 for w in words if w.endswith("لا") and len(w) > 3 or w.endswith("لاو"))
    # Texte à l'envers : plus aucun mot ne commence par « ال » alors que des mots se terminent par « لا » (= « ال » retourné).
    if len(words) >= 4 and reversed_ >= 1 and normal == 0:
        return text[::-1]
    if reversed_ >= 3 and reversed_ > normal * 2:
        return text[::-1]
    return text


def fix_rtl_script(script: dict) -> dict:
    script["title"] = fix_rtl(script.get("title", ""))
    for sc in script.get("scenes", []):
        sc["narration"] = fix_rtl(sc.get("narration", ""))
    script["claims"] = [fix_rtl(c) for c in script.get("claims", [])]
    return script


def pick_llm(keys: dict, claude_model: str) -> tuple[str, str]:
    """Anthropic si une clé existe, sinon Gemini (palier gratuit). Retourne (clé, modèle)."""
    if keys.get("anthropic"):
        return keys["anthropic"], claude_model
    if keys.get("gemini"):
        from ..config import get_settings

        return keys["gemini"], get_settings().gemini_model
    return "", claude_model


_COOLDOWN: dict[str, float] = {}


def _gemini_json(api_key: str, model: str, system: str, user: str, max_tokens: int):
    import time

    import httpx

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        # Marge large : les modèles « thinking » comptent leur réflexion dans la limite de sortie.
        "generationConfig": {"responseMimeType": "application/json", "maxOutputTokens": min(max_tokens * 4, 30000), "temperature": 0.8},
    }
    from ..config import get_settings

    models = [model] + [m.strip() for m in get_settings().gemini_fallback_models.split(",") if m.strip() and m.strip() != model]
    r, errors = None, []
    for round_ in range(2):  # 2 tours : si tous les modèles sont saturés, on patiente une fois puis on réessaie
        for m in models:
            if _COOLDOWN.get(m, 0) > time.time():
                continue
            for attempt in range(2):
                r = httpx.post(f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent", headers={"x-goog-api-key": api_key}, json=body, timeout=180)
                if r.status_code in (500, 503) and attempt == 0:
                    time.sleep(6)
                    continue
                break
            if r.status_code == 200:
                break
            if r.status_code == 429:  # quota de CE modèle atteint : on passe au suivant (quotas séparés par modèle)
                _COOLDOWN[m] = time.time() + 120
                errors.append(f"{m}: 429")
                continue
            errors.append(f"{m}: {r.status_code}")
            if r.status_code in (400, 401, 403):  # clé ou requête invalide : inutile d'essayer les autres
                raise LLMError(f"Gemini {r.status_code}: {r.text[:300]}")
        if r is not None and r.status_code == 200:
            break
        if round_ == 0:
            time.sleep(25)
            _COOLDOWN.clear()
    if r is None or r.status_code != 200:
        raise LLMError("Gemini : quota gratuit atteint sur tous les modèles essayés (" + ", ".join(errors[-6:]) + "). Réessayez dans quelques minutes ou demain. " + (getattr(r, "text", "") or "")[:200])
    j = r.json()
    cands = j.get("candidates") or []
    if not cands:
        raise LLMError("Gemini : réponse vide (contenu bloqué ou quota)")
    text = "".join(p.get("text", "") for p in cands[0].get("content", {}).get("parts", []))
    u = j.get("usageMetadata", {})
    return parse_json(text), u.get("promptTokenCount", 0), u.get("candidatesTokenCount", 0) + u.get("thoughtsTokenCount", 0)


def ask_json(api_key: str, model: str, system: str, user: str, max_tokens: int = 4000):
    if not api_key:
        raise LLMError("Aucune clé IA : ajoutez une clé Gemini (gratuite) ou Anthropic dans Réglages > Clés API")
    if model.startswith("gemini"):
        return _gemini_json(api_key, model, system, user, max_tokens)
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    r = client.messages.create(
        model=model, max_tokens=max_tokens, system=system, messages=[{"role": "user", "content": user}]
    )
    text = "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
    return parse_json(text), r.usage.input_tokens, r.usage.output_tokens


def lang_label(code: str) -> str:
    if code == "ary":
        return "Moroccan Arabic (Darija), written in Arabic script, natural spoken register"
    if code == "ar":
        return "Modern Standard Arabic (Fusha), fully diacritics-free but clear and natural"
    return VIDEO_LANGS.get(code, code)


def gen_ideas(key, model, niche, category, language, count, recent_topics, trend_titles):
    system = (
        "You are a YouTube content strategist. Propose original, specific video topics. "
        "NEVER claim a topic is trending unless it is supported by the provided trend signals; "
        "otherwise do not use the word 'trending'. Write every text field in the language given in 'language_of_titles' and in no other language. Output JSON only."
    )
    user = json.dumps(
        {
            "niche": niche,
            "category": category,
            "language_of_titles": lang_label(language),
            "count": count,
            "avoid_topics": recent_topics[-30:],
            "trend_signals_from_youtube_mostPopular": trend_titles[:25],
            "schema": {"ideas": [{"topic": "str", "angle": "str", "hook": "str", "based_on_trend_signal": "bool"}]},
        },
        ensure_ascii=False,
    )
    data, i, o = ask_json(key, model, system, user, 2000)
    ideas = data.get("ideas", data) if isinstance(data, dict) else data
    return ideas, i, o


def gen_script(key, model, topic, niche, params):
    lang, dur = params["language"], int(params["duration"])
    words, n_scenes = word_budget(dur, lang, params.get("voice_speed", 1.0)), scene_plan(dur, params["format"])
    system = (
        "You write narration scripts for YouTube videos. Rules: strong hook in the first 2-3 seconds; "
        "clear intro, development, conclusion; natural spoken language (no stage directions, no emojis, no hashtags in narration); "
        "each scene is ONE complete idea (a full sentence or two, never cut mid-sentence), so scenes flow like a continuous story; no repetition; only state facts you are confident are true, never invent statistics, quotes or sources; "
        "list every checkable factual claim in 'claims'. Add a call to action that fits the content. "
        "LANGUAGE RULE: write 'title', every 'narration', 'visual_description' and every item of 'claims' ONLY in the language given in "
        "'narration_language'; never mix in English or any other language. The single exception is 'visual_query', which must be English "
        "because it is used to search a stock footage library. Output JSON only."
    )
    user = json.dumps(
        {
            "topic": topic,
            "niche": niche,
            "category": params.get("category"),
            "audience": params.get("audience"),
            "narration_language": lang_label(lang),
            "target_duration_seconds": dur,
            "total_narration_words_max": words,
            "number_of_scenes": n_scenes,
            "visual_style": params.get("style"),
            "schema": {
                "title": "str",
                "scenes": [
                    {
                        "narration": "spoken text of the scene",
                        "visual_query": "2-4 ENGLISH keywords for a stock footage search: a concrete, filmable, literal scene (people, hands, objects, nature, city); never abstract ideas, never text/logos; all scenes must be visually DIFFERENT from each other and consistent in mood",
                        "visual_description": "one sentence describing the ideal image",
                    }
                ],
                "claims": ["factual claim to verify"],
            },
        },
        ensure_ascii=False,
    )
    data, i, o = ask_json(key, model, system, user, 6000)
    scenes = [s for s in data.get("scenes", []) if s.get("narration", "").strip()]
    if not scenes:
        raise LLMError("Le script généré ne contient aucune scène")
    script = {"title": data.get("title", topic), "scenes": scenes, "claims": data.get("claims", [])}
    return (fix_rtl_script(script) if lang in ("ar", "ary") else script), i, o


def review_script(key, model, script: dict, params):
    system = (
        "You are a meticulous script editor. Fix repetitions, incoherence and weak transitions, keep the same JSON structure "
        "and the same number of scenes, keep length within +/-10%, remove any statement you cannot stand behind and add it to 'claims' "
        "if it needs verification. Keep the SAME language as the input for title, narration and claims (do not translate; only 'visual_query' stays English). "
        "Output JSON only."
    )
    data, i, o = ask_json(key, model, system, json.dumps(script, ensure_ascii=False), 6000)
    if not data.get("scenes"):
        return script, i, o
    return {"title": data.get("title", script["title"]), "scenes": data["scenes"], "claims": data.get("claims", script["claims"])}, i, o


def gen_seo(key, model, script_text, title_hint, params):
    system = (
        "You write YouTube metadata. No keyword stuffing, no misleading claims, hashtags and tags must be relevant. "
        "LANGUAGE RULE: write titles, description, hashtags, tags, keywords, thumbnail_text and thumbnail_idea ONLY in the language given in 'language' "
        "(never in English unless that is the language); only 'file_name' is ASCII kebab-case and 'category' is one of the listed English codes. Output JSON only."
    )
    user = json.dumps(
        {
            "script": script_text[:6000],
            "working_title": title_hint,
            "language": lang_label(params["language"]),
            "is_short": params["format"] != "16:9" and int(params["duration"]) <= 180,
            "schema": {
                "titles": ["3 distinct titles, each max 90 chars"],
                "description": "professional description, first 2 lines hook the viewer, max 1500 chars",
                "hashtags": ["max 5, without #"],
                "tags": ["10-15 relevant tags"],
                "keywords_main": ["str"],
                "keywords_secondary": ["str"],
                "thumbnail_text": "max 4 words, punchy",
                "thumbnail_idea": "one sentence",
                "file_name": "kebab-case ascii, max 60 chars",
                "category": "one of: facts, science, history, tech_ai, general_culture, mystery, education, storytelling, news",
            },
        },
        ensure_ascii=False,
    )
    return ask_json(key, model, system, user, 2500)


def sanitize_seo(seo: dict, fallback_title: str, is_short: bool) -> dict:
    titles = [t.strip()[:100] for t in seo.get("titles", []) if isinstance(t, str) and t.strip()] or [fallback_title[:100]]
    tags, total = [], 0
    for t in dict.fromkeys(x.strip() for x in seo.get("tags", []) if isinstance(x, str) and x.strip()):
        if total + len(t) + 1 > 450:
            break
        tags.append(t)
        total += len(t) + 1
    hashtags = [h.lstrip("#").replace(" ", "") for h in seo.get("hashtags", []) if isinstance(h, str) and h.strip()][:5]
    if is_short and "Shorts" not in hashtags:
        hashtags = hashtags[:4] + ["Shorts"]
    desc = (seo.get("description") or "").strip()[:4500]
    desc = (desc + "\n\n" + " ".join("#" + h for h in hashtags)).strip()
    fname = re.sub(r"[^a-z0-9]+", "-", (seo.get("file_name") or "video").lower()).strip("-")[:60] or "video"
    return {
        "titles": titles,
        "title": titles[0],
        "description": desc,
        "hashtags": hashtags,
        "tags": tags,
        "keywords_main": seo.get("keywords_main", [])[:5],
        "keywords_secondary": seo.get("keywords_secondary", [])[:10],
        "thumbnail_text": (seo.get("thumbnail_text") or titles[0])[:40],
        "thumbnail_idea": seo.get("thumbnail_idea", ""),
        "file_name": fname,
        "category": seo.get("category", "education"),
    }
