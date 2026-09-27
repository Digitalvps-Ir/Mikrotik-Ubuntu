"""Render the original README animation: python assets/render_flow.py."""

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import math

HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "boot-flow.gif"
WIDTH, HEIGHT = 780, 160
SCALE = 2
FRAME_COUNT = 30


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    name = "segoeuib.ttf" if bold else "segoeui.ttf"
    windows_font = Path("C:/Windows/Fonts") / name
    if windows_font.exists():
        return ImageFont.truetype(str(windows_font), size * SCALE)
    return ImageFont.truetype("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf", size * SCALE)


def draw_frame(frame: int) -> Image.Image:
    w, h = WIDTH * SCALE, HEIGHT * SCALE
    im = Image.new("RGB", (w, h), "#0d1729")
    d = ImageDraw.Draw(im)
    s = SCALE

    for y in range(h):
        ratio = y / h
        d.line((0, y, w, y), fill=(int(13 + 9 * ratio), int(23 + 18 * ratio), int(41 + 23 * ratio)))
    for x in range(0, w, 32 * s):
        d.line((x, 0, x, h), fill="#203348", width=1)
    for y in range(0, h, 32 * s):
        d.line((0, y, w, y), fill="#203348", width=1)
    d.rounded_rectangle((2 * s, 2 * s, w - 3 * s, h - 3 * s), radius=18 * s, outline="#3f687b", width=2 * s)

    d.text((27 * s, 14 * s), "Digitalvps.ir", fill="#87efdf", font=font(14, True))
    d.text((183 * s, 15 * s), "ONE-TIME OFFLINE INSTALL", fill="#91abc3", font=font(12, True))

    centers = (112, 390, 668)
    labels = (("UBUNTU", "prepare image"), ("RAM INSTALLER", "verify + write"), ("ROUTEROS", "first boot"))
    active = (frame // 10) % 3
    pulse = (math.sin(frame * math.pi / 5) + 1) / 2

    d.line((centers[0] * s, 79 * s, centers[2] * s, 79 * s), fill="#365b70", width=4 * s)
    progress_x = centers[0] + (centers[2] - centers[0]) * frame / (FRAME_COUNT - 1)
    d.line((centers[0] * s, 79 * s, progress_x * s, 79 * s), fill="#55ddcd", width=4 * s)
    d.ellipse(((progress_x - 6) * s, 73 * s, (progress_x + 6) * s, 85 * s), fill="#b7fff1")

    for index, x in enumerate(centers):
        focus = index == active
        r = (26 + 3 * pulse) if focus else 25
        edge = "#5ff1d7" if focus else "#80a8d6"
        fill = "#1c4d55" if focus else "#213c58"
        d.ellipse(((x - r) * s, (79 - r) * s, (x + r) * s, (79 + r) * s), fill=fill, outline=edge, width=3 * s)
        if index == 0:
            d.line(((x - 10) * s, 78 * s, (x + 10) * s, 78 * s), fill="#e8f6ff", width=2 * s)
            d.line(((x - 10) * s, 85 * s, (x + 10) * s, 85 * s), fill="#e8f6ff", width=2 * s)
            d.line((x * s, 67 * s, x * s, 92 * s), fill="#e8f6ff", width=2 * s)
        elif index == 1:
            d.line(((x - 11) * s, 79 * s, (x - 3) * s, 87 * s, (x + 13) * s, 69 * s), fill="#e8fff9", width=4 * s, joint="curve")
        else:
            points = [(x * s, 64 * s), ((x + 13) * s, 72 * s), ((x + 13) * s, 87 * s), (x * s, 94 * s), ((x - 13) * s, 87 * s), ((x - 13) * s, 72 * s)]
            d.polygon(points, outline="#e8f6ff")
        title, subtitle = labels[index]
        box = d.textbbox((0, 0), title, font=font(14, True))
        d.text((x * s - (box[2] - box[0]) / 2, 112 * s), title, fill="#eaf7ff" if focus else "#bbccdf", font=font(14, True))
        box = d.textbbox((0, 0), subtitle, font=font(11))
        d.text((x * s - (box[2] - box[0]) / 2, 133 * s), subtitle, fill="#8debd9" if focus else "#8ea9c0", font=font(11))

    return im.resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS)


frames = [draw_frame(i) for i in range(FRAME_COUNT)]
frames[0].save(OUTPUT, save_all=True, append_images=frames[1:], duration=85, loop=0, optimize=True, disposal=2)
print(f"Wrote {OUTPUT} ({OUTPUT.stat().st_size:,} bytes)")
