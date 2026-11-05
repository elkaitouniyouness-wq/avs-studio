"""Tests purs (aucune dépendance externe) : options, parsing JSON IA, SEO, découpe de sous-titres."""
import pytest

from app import options as O
from app.services import llm, render


def test_video_size_formats():
    assert O.video_size("9:16", "1080p") == (1080, 1920)
    assert O.video_size("16:9", "1080p") == (1920, 1080)
    assert O.video_size("1:1", "720p") == (720, 720)
    assert O.video_size("9:16", "4k") == (2160, 3840)
    assert O.video_size("16:9", "1080p", draft=True) == (852, 480)


def test_word_budget_scales_with_duration():
    assert O.word_budget(60, "fr") > O.word_budget(30, "fr") > O.word_budget(8, "fr") >= 12
    assert O.word_budget(60, "ar") < O.word_budget(60, "en")


def test_scene_plan_shorter_is_faster_cut():
    assert O.scene_plan(30, "9:16") > 5
    assert O.scene_plan(600, "16:9") < O.scene_plan(60, "16:9") * 10


def test_resolve_voice_gender_and_clamp():
    v = O.resolve_voice("fr", "female", "energetic", 5.0)
    assert v["gender"] == "FEMALE" and v["language_code"] == "fr-FR" and v["rate"] <= 1.4
    assert O.resolve_voice("ary", "male", "calm")["language_code"] == "ar-XA"


def test_parse_json_variants():
    assert llm.parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert llm.parse_json('Voici: {"a": [1,2]} fin') == {"a": [1, 2]}
    with pytest.raises(llm.LLMError):
        llm.parse_json("pas de json")


def test_sanitize_seo_limits():
    seo = {"titles": ["x" * 300], "tags": ["t%d" % i * 20 for i in range(100)], "hashtags": ["#a b", "c", "d", "e", "f", "g"], "description": "d" * 9000}
    out = llm.sanitize_seo(seo, "fallback", is_short=True)
    assert len(out["title"]) <= 100
    assert sum(len(t) + 1 for t in out["tags"]) <= 450
    assert len(out["hashtags"]) <= 5 and "Shorts" in out["hashtags"]
    assert len(out["description"]) <= 5000


def test_subtitle_cues_cover_scene_exactly():
    scenes = [{"narration": "un deux trois quatre cinq six sept", "start": 2.0, "dur": 6.0}]
    cues = render.build_cues(scenes, 3)
    assert cues[0][0] == 2.0 and abs(cues[-1][1] - 8.0) < 1e-6
    assert all(b > a for a, b, _ in cues) and len(cues) == 3


def test_pick_llm_prefers_anthropic_then_none():
    assert llm.pick_llm({"anthropic": "k", "gemini": "g"}, "claude-x") == ("k", "claude-x")
    assert llm.pick_llm({}, "claude-x") == ("", "claude-x")
    with pytest.raises(llm.LLMError):
        llm.ask_json("", "claude-x", "s", "u")


def test_tts_falls_back_to_edge(monkeypatch):
    import sys
    import types

    from app.services import tts

    mod = types.ModuleType("edge_tts")

    class C:
        def __init__(self, t, v, rate):
            self.v, self.rate = v, rate

        async def stream(self):
            yield {"type": "audio", "data": b"mp3"}

    mod.Communicate = C
    monkeypatch.setitem(sys.modules, "edge_tts", mod)
    monkeypatch.setattr(tts, "_gemini", lambda *a, **k: (_ for _ in ()).throw(tts.TTSError("429")))
    data, provider = tts.synthesize({"gemini": "k"}, "salam", O.resolve_voice("ary", "male", "energetic"))
    assert (data, provider) == (b"mp3", "edge")


def test_fix_rtl_only_flips_reversed_arabic():
    rev = "؟كسفن غدغدت ةيناث يلملا ريخأت كلعجي فيك :ةعدخ"
    assert llm.fix_rtl(rev) == "خدعة: كيف يجعلك تأخير الملي ثانية تدغدغ نفسك؟"
    ok = "جرب الآن أن تدغدغ نفسك تحت إبطك أو في قدمك"
    assert llm.fix_rtl(ok) == ok


def test_tts_provider_chain_order(monkeypatch):
    from app.services import tts

    monkeypatch.delenv("EDGE_TTS", raising=False)
    assert tts.provider_chain({"gemini": "k", "google_tts": "g"}) == ["gemini", "google-chirp", "google-standard", "edge"]
    monkeypatch.setenv("EDGE_TTS", "false")
    assert tts.provider_chain({}) == []
