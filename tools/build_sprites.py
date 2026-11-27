"""Bakes every pet's animation frames into one sprite-sheet PNG per pet and size in desktop_pet/assets/ from the pictures in tools/pets/<pet>/.

Per pet: open.png (required), closed.png and happy.png (optional; if missing they are made from open.png using the
eye positions in PETS below). Pictures may have a transparent background, or a flat/gradient MAGENTA background
that is removed automatically. Needs Pillow, NumPy, OpenCV and SciPy. The app itself needs none of them.
"""
import math
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

HERE = Path(__file__).parent
OUT = HERE.parent / "desktop_pet" / "assets"
KEY = (1, 1, 1)                      # transparent colour used by the app's windows
HEIGHTS = (115, 170)                 # pet height in pixels at 100% / 150%+ display scaling
PAD_X, PAD_Y = 1.28, 1.22            # canvas padding so tilts and hops are not clipped

# Eye centres and radii (in 1024-px pictures) used to draw closed / happy eyes when those pictures are not supplied.
PETS = {
    "mochi": {"fill_holes": False},                                   # calico kitten (the tail curl is a real gap)
    "remi": {"eyes": [((416, 386), (50, 48)), ((621, 349), (46, 44))], "lash": (62, 40, 34), "spill": 0.7},   # sloth
    "finn": {"cool": 0.85},                                                      # fennec fox (teal background)
    "pogo": {},                                                        # porcupine
    "boba": {"spill": 0.4},                                            # hamster
}


# ----------------------------------------------------------------------------- picture preparation

def erase_sparkle(img):
    """Gemini puts a small sparkle watermark in the bottom-right corner: paint it out."""
    w, h = img.size
    mask = np.zeros((h, w), np.uint8)
    cv2.rectangle(mask, (int(w * 0.83), int(h * 0.84)), (int(w * 0.945), int(h * 0.935)), 255, -1)
    rgb = cv2.inpaint(np.array(img.convert("RGB")), mask, 7, cv2.INPAINT_TELEA)
    return Image.fromarray(rgb)


def has_real_alpha(img):
    a = np.array(img.convert("RGBA"))[..., 3]
    return (a < 250).mean() > 0.02


def background_kind(img):
    c = np.median(np.array([np.array(img.convert("RGB"))[y, x] for y in (3, -4) for x in (3, -4)]), axis=0)
    r, g, b = [int(v) for v in c]
    return "teal" if (min(g, b) - r) > 40 else "magenta"


def chroma_alpha(img, fill_holes=True):
    """Alpha for a pet on a flat/gradient coloured studio background (magenta or teal, with soft shadows).
    Magenta: red and blue far above green. Teal: green and blue far above red. Fur and skin tones never are."""
    rgb = np.array(img.convert("RGB")).astype(np.int32)
    if background_kind(img) == "teal":
        background = (np.minimum(rgb[..., 1], rgb[..., 2]) - rgb[..., 0]) > 40
    else:
        background = ((np.minimum(rgb[..., 0], rgb[..., 2]) - rgb[..., 1]) > 95) & (rgb[..., 1] < 120)
    fg = (~background).astype(np.uint8)
    fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(fg, connectivity=8)
    if count > 1:
        keep = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        fg = (labels == keep).astype(np.uint8)
    if fill_holes:
        fg = ndimage.binary_fill_holes(fg).astype(np.uint8)
    else:                                                                   # only close tiny specks
        holes = (fg == 0).astype(np.uint8)
        n, lab, st, _ = cv2.connectedComponentsWithStats(holes, connectivity=4)
        for i in range(1, n):
            if st[i, cv2.CC_STAT_AREA] < 400:
                fg[lab == i] = 1
    alpha = (fg * 255).astype(np.uint8)
    alpha = cv2.erode(alpha, np.ones((3, 3), np.uint8), iterations=2)          # shave the coloured fringe
    return cv2.GaussianBlur(alpha, (0, 0), 1.0)


def despill(rgb, alpha, kind="magenta"):
    """Remove the coloured glow along the outline of the pet."""
    transparent = (alpha < 128).astype(np.uint8)
    band = (cv2.dilate(transparent, np.ones((13, 13), np.uint8)) == 1) & (transparent == 0)
    c = rgb.astype(np.int32)
    if kind == "teal":
        spill = np.maximum(0, np.minimum(c[..., 1], c[..., 2]) - c[..., 0])
        chans = (1, 2)
    else:
        spill = np.maximum(0, np.minimum(c[..., 0], c[..., 2]) - c[..., 1])
        chans = (0, 2)
    for ch in chans:
        c[..., ch] = np.where(band, c[..., ch] - (spill * 0.9).astype(np.int32), c[..., ch])
    return np.clip(c, 0, 255).astype(np.uint8)


def make_eyes(img, eyes, lash, mode):
    """Cover the open eyes with fur inpainted from the surroundings and draw closed ('closed') or happy arched eyes."""
    arr = np.array(img.convert("RGB"))
    mask = np.zeros(arr.shape[:2], np.uint8)
    for (cx, cy), (rx, ry) in eyes:
        cv2.ellipse(mask, (cx, cy), (rx + 8, ry + 8), 0, 0, 360, 255, -1)
    filled = cv2.inpaint(arr, mask, 13, cv2.INPAINT_TELEA)
    blurred = cv2.GaussianBlur(filled, (0, 0), 2.0)
    filled = np.where(mask[..., None] > 0, blurred, filled)
    out = Image.fromarray(filled)
    d = ImageDraw.Draw(out)
    for (cx, cy), (rx, ry) in eyes:
        if mode == "closed":
            d.arc((cx - rx + 2, cy - ry + 6, cx + rx - 2, cy + ry + 4), 25, 155, fill=lash, width=7)
        else:
            d.arc((cx - rx + 4, cy - ry // 2 + 10, cx + rx - 4, cy + ry + 16), 205, 335, fill=lash, width=7)
    return out


def load_pet(name):
    cfg = PETS[name]
    folder = HERE / "pets" / name
    raw = {}
    for pose in ("open", "closed", "happy"):
        p = folder / f"{pose}.png"
        if p.exists():
            raw[pose] = Image.open(p).convert("RGBA")
    if "open" not in raw:
        sys.exit(f"tools/pets/{name}/open.png is missing.")
    size = raw["open"].size
    transparent_bg = has_real_alpha(raw["open"])
    rgb_open = raw["open"].convert("RGB") if transparent_bg else erase_sparkle(raw["open"])
    for pose, mode in (("closed", "closed"), ("happy", "happy")):
        if pose not in raw:
            if cfg.get("eyes"):
                print(f"note: {name}/{pose}.png not found, drawing it from open.png")
                raw[pose] = make_eyes(rgb_open, cfg["eyes"], cfg["lash"], mode).convert("RGBA")
            else:
                print(f"note: {name}/{pose}.png not found, using open.png")
                raw[pose] = raw["open"].copy()
    out = {}
    shared = None
    for pose, img in raw.items():
        if img.size != size:
            img = img.resize(size, Image.LANCZOS)
        if has_real_alpha(img):
            out[pose] = img
            continue
        img = erase_sparkle(img) if pose != "open" or not transparent_bg else img
        if shared is None:
            shared = chroma_alpha(rgb_open, cfg.get("fill_holes", True))
        kind = background_kind(rgb_open)
        rgb = despill(np.array(img.convert("RGB")), shared, kind)
        if cfg.get("spill"):                                     # studio light tints the fur: pull blue back to green
            c = rgb.astype(np.int32)
            c[..., 2] -= (np.maximum(0, c[..., 2] - c[..., 1]) * cfg["spill"]).astype(np.int32)
            rgb = np.clip(c, 0, 255).astype(np.uint8)
        if cfg.get("cool"):                                      # teal studio light: warm the cool shadows back to fur colours
            c = rgb.astype(np.int32)
            c[..., 2] -= (np.maximum(0, c[..., 2] - c[..., 0]) * cfg["cool"]).astype(np.int32)
            c[..., 1] -= (np.maximum(0, c[..., 1] - c[..., 0]) * cfg["cool"] * 0.55).astype(np.int32)
            rgb = np.clip(c, 0, 255).astype(np.uint8)
        out[pose] = Image.fromarray(np.dstack([rgb, shared]), "RGBA")
    box = out["open"].getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox()
    m = 8
    box = (max(0, box[0] - m), max(0, box[1] - m), min(size[0], box[2] + m), min(size[1], box[3] + m))
    return {k: v.crop(box) for k, v in out.items()}


# ----------------------------------------------------------------------------- animation frames

def frame(src, dy=0.0, tilt=0.0, sx=1.0, sy=1.0, dx=0.0):
    """Place the sprite on a padded canvas and apply squash/tilt/hop around the feet. Returns RGBA at canvas size."""
    BW, BH = src.size
    cw, ch = int(BW * PAD_X), int(BH * PAD_Y)
    canvas = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    ox, oy = (cw - BW) // 2, ch - BH - int(BH * 0.03)
    canvas.paste(src, (ox, oy), src)
    px, py = cw / 2, ch - BH * 0.03
    a = math.radians(tilt)
    S = np.array([[sx, 0, 0], [0, sy, 0], [0, 0, 1]], float)
    R = np.array([[math.cos(a), -math.sin(a), 0], [math.sin(a), math.cos(a), 0], [0, 0, 1]], float)
    T1 = np.array([[1, 0, px], [0, 1, py], [0, 0, 1]], float)
    T0 = np.array([[1, 0, -px], [0, 1, -py], [0, 0, 1]], float)
    Tm = np.array([[1, 0, dx * BW], [0, 1, -dy * BH], [0, 0, 1]], float)
    M = (Tm @ T1 @ R @ S @ T0)[:2]
    arr = np.array(canvas).astype(np.float32)
    # colours of invisible pixels must not influence the edge: spread the nearest visible colour outwards first
    opaque = arr[..., 3] > 127
    if opaque.any():
        idx = ndimage.distance_transform_edt(~opaque, return_distances=False, return_indices=True)
        arr[..., :3] = arr[..., :3][tuple(idx)]
    warped_rgb = cv2.warpAffine(arr[..., :3], M, (cw, ch), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    warped_a = cv2.warpAffine(arr[..., 3], M, (cw, ch), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    return Image.fromarray(np.dstack([np.clip(warped_rgb, 0, 255), np.clip(warped_a, 0, 255)]).astype(np.uint8), "RGBA")


ROWS = ("idle", "talk", "happy", "blink")      # sheet layout: one row per animation, up to COLS frames per row
COLS = 6


def to_key_image(img, ref_height, height):
    """Scale to `height` px, then put on the transparent key colour using a hard edge. Blending the edge with the key
    colour is what used to draw a dark outline around the pet, so the edge is a clean cut instead."""
    f = height / ref_height
    size = (max(1, round(img.width * f)), max(1, round(img.height * f)))
    arr = np.array(img)
    rgb = cv2.resize(arr[..., :3], size, interpolation=cv2.INTER_AREA)
    alpha = cv2.resize(arr[..., 3], size, interpolation=cv2.INTER_AREA)
    keep = alpha > 120
    out = np.empty_like(rgb)
    out[:] = KEY
    out[keep] = np.maximum(rgb[keep], 3)                 # never equal the key colour inside the sprite
    return Image.fromarray(out, "RGB")


def cycle(n, fn):
    return [fn(2 * math.pi * i / n) for i in range(n)]


def visual_size(poses):
    """sqrt(area)/height of the pet, used to make every pet look about equally big on screen."""
    alpha = np.array(poses["open"].getchannel("A")) > 127
    return math.sqrt(alpha.sum()) / poses["open"].height


def build_pet(name, factor=1.0):
    poses = load_pet(name)
    o, c, h = poses["open"], poses["closed"], poses["happy"]
    ref = o.height
    anims = {
        "idle": cycle(4, lambda t: frame(o, sy=1 + 0.012 * math.sin(t), sx=1 - 0.006 * math.sin(t))),
        "talk": cycle(6, lambda t: frame(o, dy=0.012 * (1 + math.sin(2 * t)), tilt=2.5 * math.sin(t), sy=1 + 0.012 * math.sin(2 * t))),
        "happy": [frame(h, dy=0.10 * math.sin(math.pi * i / 5), tilt=(-4 if i % 2 else 4) * math.sin(math.pi * i / 5),
                        sy=1 + 0.03 * math.cos(math.pi * i / 5), sx=1 - 0.02 * math.cos(math.pi * i / 5)) for i in range(6)],
        "blink": [frame(c)],
    }
    for height in HEIGHTS:
        cells = {anim: [to_key_image(im, ref, round(height * factor)) for im in frames] for anim, frames in anims.items()}
        cw, ch = cells["idle"][0].size
        sheet = Image.new("RGB", (COLS * cw, len(ROWS) * ch), KEY)
        for row, anim in enumerate(ROWS):
            for col, im in enumerate(cells[anim]):
                sheet.paste(im, (col * cw, row * ch))
        sheet.save(OUT / f"{name}_{height}.png", optimize=True)     # one sprite sheet per pet and size
    return poses


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.png"):
        old.unlink()
    sizes = {name: visual_size(load_pet(name)) for name in PETS}
    for name in PETS:
        factor = min(1.3, max(0.75, sizes["mochi"] / sizes[name]))
        print(f"{name}: size factor {factor:.2f}")
        poses = build_pet(name, factor)
        if name == "mochi":                      # app / tray icon: the first pet's face
            base = poses["open"]
            face = base.crop((0, 0, base.width, int(base.height * 0.62)))
            side = max(face.size)
            icon = Image.new("RGBA", (side, side), (0, 0, 0, 0))
            icon.paste(face, ((side - face.width) // 2, (side - face.height) // 2), face)
            icon.resize((256, 256), Image.LANCZOS).save(OUT / "app.ico", sizes=[(256, 256), (64, 64), (48, 48), (32, 32), (24, 24), (16, 16)])
    print("sprite sheets written:", len(list(OUT.glob("*_*.png"))))


if __name__ == "__main__":
    main()
