"""Moteur de montage FFmpeg : segments par scène (vidéo/image + narration), concaténation, sous-titres ASS brûlés,
musique avec ducking, normalisation du volume, export MP4. Dépend uniquement de ffmpeg/ffprobe."""
import json
import re
import subprocess
from pathlib import Path

FPS = 30
FONT_DIRS = "/usr/share/fonts"


class RenderError(Exception):
    pass


def run(cmd: list[str], cwd: str | None = None, timeout: int = 1800):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise RenderError(f"{cmd[0]} a échoué: {p.stderr[-800:]}")
    return p


def probe(path: str) -> dict:
    p = run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)])
    data = json.loads(p.stdout)
    streams = data.get("streams", [])
    v = next((s for s in streams if s["codec_type"] == "video"), None)
    a = next((s for s in streams if s["codec_type"] == "audio"), None)
    return {
        "duration": float(data.get("format", {}).get("duration", 0) or 0),
        "has_video": v is not None,
        "has_audio": a is not None,
        "width": v.get("width") if v else None,
        "height": v.get("height") if v else None,
    }


def mean_volume_db(path: str) -> float | None:
    p = subprocess.run(["ffmpeg", "-i", str(path), "-af", "volumedetect", "-vn", "-f", "null", "-"], capture_output=True, text=True)
    m = re.search(r"mean_volume:\s*(-?[\d.]+) dB", p.stderr)
    return float(m.group(1)) if m else None


def make_segment(kind: str, media: str, audio: str, dur: float, size: tuple[int, int], out: str, tail: float = 0.12):
    """Une scène = média recadré au format + narration. Image -> mouvement de caméra lent (zoom)."""
    w, h = size
    total = round(dur + tail, 3)
    # Pas de fondu au noir entre scènes (effet « clignotement ») : coupes nettes calées sur la narration.
    common_tail = f"fps={FPS},format=yuv420p"
    if kind == "video":
        pre = ["-stream_loop", "-1", "-i", media]
        vf = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1,{common_tail}"
    else:
        big_w, big_h = int(w * 1.5) // 2 * 2, int(h * 1.5) // 2 * 2
        frames = int(total * FPS) + 1
        pre = ["-loop", "1", "-framerate", str(FPS), "-i", media]
        vf = (
            f"scale={big_w}:{big_h}:force_original_aspect_ratio=increase,crop={big_w}:{big_h},"
            f"zoompan=z='min(zoom+0.0007,1.25)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={w}x{h}:fps={FPS},setsar=1,{common_tail}"
        )
    cmd = (
        ["ffmpeg", "-y", "-v", "error"]
        + pre
        + ["-i", audio, "-t", str(total), "-vf", vf, "-af", f"afade=t=in:st=0:d=0.02,afade=t=out:st={max(total - 0.04, 0):.3f}:d=0.04,apad,aresample=44100", "-map", "0:v:0", "-map", "1:a:0"]
        + ["-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ac", "2", "-ar", "44100", "-shortest", out]
    )
    run(cmd)
    return total


def trim_silence(path: str):
    """Retire le silence au début et à la fin d'un fichier voix (sinon chaque scène « respire » 0,3 s : rendu haché)."""
    tmp = path + ".trim.mp3"
    af = "silenceremove=start_periods=1:start_silence=0.03:start_threshold=-48dB,areverse,silenceremove=start_periods=1:start_silence=0.03:start_threshold=-48dB,areverse"
    p = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", path, "-af", af, "-c:a", "libmp3lame", "-b:a", "128k", tmp], capture_output=True)
    if p.returncode == 0 and Path(tmp).exists() and Path(tmp).stat().st_size > 800:
        Path(tmp).replace(path)
    else:
        Path(tmp).unlink(missing_ok=True)


def concat_segments(segments: list[str], out: str, workdir: str):
    lst = Path(workdir) / "concat.txt"
    lst.write_text("".join(f"file '{Path(s).resolve()}'\n" for s in segments))
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", out])


# ---------- Sous-titres ----------
def _ts(t: float) -> str:
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def _srt_ts(t: float) -> str:
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{s:06.3f}".replace(".", ",")


def split_chunks(text: str, max_words: int) -> list[str]:
    words = text.split()
    return [" ".join(words[i : i + max_words]) for i in range(0, len(words), max_words)] or [""]


def build_cues(scenes: list[dict], max_words: int) -> list[tuple[float, float, str]]:
    """scenes: [{narration, start, dur}] -> cues réparties proportionnellement à la longueur des morceaux."""
    cues = []
    for s in scenes:
        chunks = split_chunks(s["narration"], max_words)
        weights = [max(len(c), 1) for c in chunks]
        total = sum(weights)
        t = s["start"]
        for c, wgt in zip(chunks, weights):
            d = s["dur"] * wgt / total
            cues.append((t, t + d, c))
            t += d
    return cues


def write_subtitles(cues, size: tuple[int, int], lang: str, ass_path: str, srt_path: str):
    w, h = size
    vertical = h > w
    fs = int((w if vertical else h) * (0.062 if vertical else 0.058))
    font = "Noto Sans Arabic" if lang in ("ar", "ary") else "DejaVu Sans"
    margin_v = int(h * (0.20 if vertical else 0.09))
    ass = (
        f"[Script Info]\nScriptType: v4.00+\nPlayResX: {w}\nPlayResY: {h}\nWrapStyle: 0\n\n"
        "[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,"
        "ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n"
        f"Style: Default,{font},{fs},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,{max(2, fs // 14)},1,2,{int(w * 0.06)},{int(w * 0.06)},{margin_v},1\n\n"
        "[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n"
    )
    srt = []
    for i, (a, b, text) in enumerate(cues, 1):
        clean = text.replace("\n", " ").replace("{", "(").replace("}", ")")
        ass += f"Dialogue: 0,{_ts(a)},{_ts(b)},Default,,0,0,0,,{clean}\n"
        srt.append(f"{i}\n{_srt_ts(a)} --> {_srt_ts(b)}\n{text}\n")
    Path(ass_path).write_text(ass, encoding="utf-8")
    Path(srt_path).write_text("\n".join(srt), encoding="utf-8")


# ---------- Mixage final ----------
def finalize(concat_path: str, out: str, workdir: str, ass_name: str | None, music: str | None, total_dur: float, draft: bool = False):
    """Brûle les sous-titres, mixe la musique (ducking sous la voix), normalise le volume, exporte en MP4."""
    vf = f"subtitles={ass_name}:fontsdir={FONT_DIRS}" if ass_name else "null"
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(Path(concat_path).resolve())]
    if music:
        cmd += ["-stream_loop", "-1", "-i", str(Path(music).resolve())]
        fc = (
            f"[0:v]{vf}[v];"
            "[0:a]asplit=2[n1][n2];"
            "[1:a]volume=0.22[m];"
            "[m][n1]sidechaincompress=threshold=0.03:ratio=10:attack=20:release=400[md];"
            "[n2][md]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-16:TP=-1.5:LRA=11[a]"
        )
    else:
        fc = f"[0:v]{vf}[v];[0:a]loudnorm=I=-16:TP=-1.5:LRA=11[a]"
    cmd += ["-filter_complex", fc, "-map", "[v]", "-map", "[a]", "-t", f"{total_dur:.3f}"]
    cmd += ["-c:v", "libx264", "-preset", "ultrafast" if draft else "medium", "-crf", "28" if draft else "20", "-pix_fmt", "yuv420p"]
    cmd += ["-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-movflags", "+faststart", str(Path(out).resolve())]
    run(cmd, cwd=workdir)


def extract_frame(video: str, out: str, at: float = 1.0):
    run(["ffmpeg", "-y", "-v", "error", "-ss", str(at), "-i", video, "-frames:v", "1", "-q:v", "2", out])
