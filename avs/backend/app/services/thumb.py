"""Miniature YouTube 1280x720 lisible sur téléphone (image de fond + texte avec contour). Arabe : reshaping + bidi."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONTS_AR = ["/usr/share/fonts/truetype/noto/NotoSansArabic-Bold.ttf", "/usr/share/fonts/opentype/noto/NotoSansArabic-Bold.ttf", "/usr/share/fonts/truetype/noto/NotoNaskhArabic-Bold.ttf"]
FONTS_LAT = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"]


def find_font(lang: str) -> str | None:
    for p in (FONTS_AR if lang in ("ar", "ary") else []) + FONTS_LAT + FONTS_AR:
        if Path(p).exists():
            return p
    return None


def shape(text: str, lang: str) -> str:
    if lang in ("ar", "ary"):
        try:
            import arabic_reshaper
            from bidi.algorithm import get_display

            return get_display(arabic_reshaper.reshape(text))
        except ImportError:
            return text
    return text


def make_thumbnail(frame_path: str, text: str, lang: str, out: str) -> str:
    W, H = 1280, 720
    src = Image.open(frame_path).convert("RGB")
    # Fond : image étirée et floutée ; premier plan : image entière centrée (gère le vertical 9:16).
    bg = src.copy()
    scale = max(W / bg.width, H / bg.height)
    bg = bg.resize((int(bg.width * scale), int(bg.height * scale)))
    bg = bg.crop(((bg.width - W) // 2, (bg.height - H) // 2, (bg.width - W) // 2 + W, (bg.height - H) // 2 + H)).filter(ImageFilter.GaussianBlur(18 if src.height > src.width else 0))
    if src.height > src.width:
        fg_h = H
        fg = src.resize((int(src.width * fg_h / src.height), fg_h))
        bg.paste(fg, ((W - fg.width) // 2, 0))
    img = bg
    # Assombrissement en bas pour la lisibilité du texte.
    shade = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shade)
    for y in range(H // 2, H):
        sd.line([(0, y), (W, y)], fill=(0, 0, 0, int(190 * (y - H // 2) / (H // 2))))
    img = Image.alpha_composite(img.convert("RGBA"), shade).convert("RGB")
    d = ImageDraw.Draw(img)
    fp = find_font(lang)
    text = shape(text.upper() if lang not in ("ar", "ary") else text, lang)
    size = 120
    while size > 40:
        font = ImageFont.truetype(fp, size) if fp else ImageFont.load_default()
        bbox = d.textbbox((0, 0), text, font=font, stroke_width=8)
        if bbox[2] - bbox[0] <= W - 120:
            break
        size -= 6
    x = (W - (bbox[2] - bbox[0])) // 2 - bbox[0]
    y = H - (bbox[3] - bbox[1]) - 70 - bbox[1]
    d.text((x, y), text, font=font, fill=(255, 221, 51), stroke_width=8, stroke_fill=(0, 0, 0))
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    img.save(out, quality=90)
    return out
