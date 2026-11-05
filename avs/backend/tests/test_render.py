"""Test réel du moteur FFmpeg sur médias synthétiques (nécessite ffmpeg dans le PATH)."""
import shutil

import pytest

from app.services import render

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg absent")


def _gen(tmp_path):
    import subprocess

    def ff(*a):
        subprocess.run(["ffmpeg", "-v", "error", "-y", *a], check=True, cwd=tmp_path)

    ff("-f", "lavfi", "-i", "testsrc2=s=640x360:d=5:r=30", "-pix_fmt", "yuv420p", "clip.mp4")
    ff("-f", "lavfi", "-i", "color=c=orange:s=800x600", "-frames:v", "1", "img.jpg")
    ff("-f", "lavfi", "-i", "sine=f=220:d=2.4", "a1.mp3")
    ff("-f", "lavfi", "-i", "sine=f=330:d=3.1", "a2.mp3")
    ff("-f", "lavfi", "-i", "sine=f=110:d=5", "music.mp3")


@pytest.mark.parametrize("size", [(540, 960), (960, 540), (640, 640)])
def test_render_pipeline_formats(tmp_path, size):
    _gen(tmp_path)
    p = lambda n: str(tmp_path / n)  # noqa: E731
    d1 = render.make_segment("video", p("clip.mp4"), p("a1.mp3"), render.probe(p("a1.mp3"))["duration"], size, p("s1.mp4"))
    d2 = render.make_segment("image", p("img.jpg"), p("a2.mp3"), render.probe(p("a2.mp3"))["duration"], size, p("s2.mp4"))
    render.concat_segments([p("s1.mp4"), p("s2.mp4")], p("cat.mp4"), str(tmp_path))
    cues = render.build_cues([{"narration": "مرحبا بكم في الفيديو", "start": 0, "dur": d1}, {"narration": "second scene here", "start": d1, "dur": d2}], 4)
    render.write_subtitles(cues, size, "ar", p("s.ass"), p("s.srt"))
    render.finalize(p("cat.mp4"), p("final.mp4"), str(tmp_path), "s.ass", p("music.mp3"), d1 + d2)
    info = render.probe(p("final.mp4"))
    assert (info["width"], info["height"]) == size
    assert info["has_audio"] and abs(info["duration"] - (d1 + d2)) < 0.3
    vol = render.mean_volume_db(p("final.mp4"))
    assert vol is not None and vol > -40
    assert "-->" in (tmp_path / "s.srt").read_text(encoding="utf-8")
