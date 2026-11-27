"""Generate the integration icon (original artwork: pendant light, light cone, water).

Usage: python scripts/make_icon.py custom_components/kessil_dongle/brand
Requires Pillow.
"""

import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

S = 2048  # supersampled canvas
u = S / 1024  # design units -> pixels
out = Path(sys.argv[1])


def P(x, y):
    return (x * u, y * u)


def vgrad(size, top, bottom, alpha_top=255, alpha_bottom=255):
    w, h = size
    g = Image.new("RGBA", (1, h))
    for y in range(h):
        t = y / max(1, h - 1)
        c = tuple(round(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        a = round(alpha_top + (alpha_bottom - alpha_top) * t)
        g.putpixel((0, y), (*c, a))
    return g.resize((w, h))


# background: deep water gradient in a rounded square
bg = vgrad((S, S), (8, 47, 82), (12, 110, 140))
mask = Image.new("L", (S, S), 0)
ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1], radius=int(230 * u), fill=255)
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
img.paste(bg, (0, 0), mask)

# light cone (warm, fading downwards)
cone_mask = Image.new("L", (S, S), 0)
ImageDraw.Draw(cone_mask).polygon([P(392, 392), P(632, 392), P(860, 820), P(164, 820)], fill=255)
cone_mask = cone_mask.filter(ImageFilter.GaussianBlur(10 * u))
cone = vgrad((S, S), (255, 214, 140), (255, 190, 110))
alpha = vgrad((1, S), (0, 0, 0), (0, 0, 0)).split()[0]
fade = Image.new("L", (1, S))
for y in range(S):
    t = min(1, max(0, (y / u - 392) / (820 - 392)))
    fade.putpixel((0, y), round(190 * (1 - t) ** 1.3))
fade = fade.resize((S, S))
cone.putalpha(Image.composite(fade, Image.new("L", (S, S), 0), cone_mask))
img = Image.alpha_composite(img, cone)


# water waves
def wave_layer(y0, amp, period, phase, color, a):
    layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    pts = [
        P(x, y0 + amp * math.sin((x / period) * 2 * math.pi + phase)) for x in range(-10, 1035, 4)
    ]
    pts += [P(1034, 1034), P(-10, 1034)]
    ImageDraw.Draw(layer).polygon(pts, fill=(*color, a))
    return layer


img = Image.alpha_composite(img, wave_layer(735, 22, 330, 0.6, (34, 211, 238), 120))
img = Image.alpha_composite(img, wave_layer(800, 18, 280, 2.4, (14, 165, 200), 170))
img = Image.alpha_composite(img, wave_layer(870, 14, 240, 4.0, (8, 80, 120), 220))

# suspension cable
d = ImageDraw.Draw(img)
d.line([P(512, -10), P(512, 250)], fill=(226, 232, 240, 255), width=int(14 * u))

# glow under the lamp
glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
ImageDraw.Draw(glow).ellipse([P(380, 350), P(644, 430)], fill=(255, 200, 120, 200))
glow = glow.filter(ImageFilter.GaussianBlur(28 * u))
img = Image.alpha_composite(img, glow)

# pendant: dome shade + warm emitter rim
d = ImageDraw.Draw(img)
d.pieslice(
    [P(352, 232), P(672, 552)], 180, 360, fill=(241, 245, 249, 255)
)  # dome (upper half circle)
d.rounded_rectangle([P(352, 380), P(672, 404)], radius=int(12 * u), fill=(203, 213, 225, 255))
d.rounded_rectangle(
    [P(380, 398), P(644, 418)], radius=int(10 * u), fill=(255, 196, 92, 255)
)  # emitter
d.ellipse([P(496, 226), P(528, 258)], fill=(203, 213, 225, 255))  # cable mount

# clip to rounded square again (glow/cone may overflow)
final = Image.new("RGBA", (S, S), (0, 0, 0, 0))
final.paste(img, (0, 0), mask)

out.mkdir(parents=True, exist_ok=True)
final.resize((512, 512), Image.LANCZOS).save(out / "icon@2x.png", optimize=True)
final.resize((256, 256), Image.LANCZOS).save(out / "icon.png", optimize=True)
print("ok")
