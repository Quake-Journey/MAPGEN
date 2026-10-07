r"""The generator's texture pack (Fable's brief 11, 2nd edition, D3; ledger row 412k).

The PO, 06.10: «а что мешает взять эти картинки как основа и подготовить текстуры которые подходят под формат игры???
и сделать аналогичные но разнообразные и вариативные, подходящие под разные условия. Это все войдет в ассеты нашего
генератора. Плюс ты можешь поискать в интернете еще сэмплов, а также нагенерировать их сам»; «главное чтоб не было
водяных знаков и прочей херни которая будет мешаться на экране в игре».

    python tools/mapgen_textures.py build   [--out DIR] [--no-fetch]   # sources -> the pack, catalogue, sheets
    python tools/mapgen_textures.py install MODDIR [--pack DIR]        # the pack into MODDIR/textures/mapgen
    python tools/mapgen_textures.py crack MODDIR NEEDS [--pack DIR]    # a map's cracked variants of its own textures

Sources, three:
* the PO's pictures - `Кратеры` (holes and cracks: MASKS) and `Поверхности` (floors and walls: textures of their own);
* Poly Haven's seamless colour maps, fetched once by family (rock, concrete, brick, metal, ground, gravel, sand,
  wood, cobblestone) into the sources folder - never into the repository;
* generated here: crack, crater, hole and soot masks from seeded procedures, any number.

Every texture is a pair in the game's format: `<name>.wal` 256x256, 8-bit in the palette of the client's own
`pics/colormap.pcx` (read from its pak), 4 mips, dithered; and `<name>.jpg` 512x512 beside it (the q2pro family takes
it as the picture of that name). Each picture is cut to what is surface only - flat bands at its edges (a photobank's
footer, a border, a caption) trimmed away, the light evened out (a vignette, a lamp's gradient), the largest centred
square - and made tileable (each edge cross-faded with the opposite one). Refused, with the reason in the catalogue: a
name of a photobank, a band that would not trim, a perspective shot, a seam left, a colour no Quake II surface has
(pink, turquoise), a picture too small. What the eye still finds on the contact sheets - the PO's - goes in
`tools/mapgen_textures_refused.json` by name and is refused at the next build.

Variants of every accepted base, named by condition so the generator can choose by it: `_dk` (darker), `_wet`
(darker, more contrast), `_moss` (green in the hollows - stone, rock, concrete, brick, ground), `_rust` (metal only),
`_soot` (blackened). Catalogue: `catalogue.json` beside the pack and in `tools/mapgen_textures_catalogue.json` (the
repository's record); contact sheets in `doc/mapgen_textures/sheets/<family>.jpg`.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import re
import shutil
import struct
import sys
import urllib.request
import zlib
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps

TOOLS = Path(__file__).resolve().parent
REPO = TOOLS.parent
PO_ROOT = Path(r"O:\Claude2\q2pro")
CRATERS = PO_ROOT / "Кратеры"
SURFACES = PO_ROOT / "Поверхности"
SOURCES = Path(r"O:\Claude2\_agent_temp\claude\mapgen_textures\sources")
OUT = Path(r"O:\Claude2\_agent_temp\claude\mapgen_textures\pack")
GAME = Path(r"O:\Claude2\q2pro-release\baseq2")
REFUSED_BY_EYE = TOOLS / "mapgen_textures_refused.json"
CATALOGUE_COPY = TOOLS / "mapgen_textures_catalogue.json"
SHEETS = REPO / "doc" / "mapgen_textures" / "sheets"
WAL, HI = 256, 512
PER_FAMILY = 10
PHOTOBANK = re.compile(r"bigstock|shutterstock|istock|depositphotos|123rf|dreamstime|alamy|freepik|adobestock|"
                       r"gettyimages|vecteezy|pngtree|stock-photo|stockphoto", re.I)
# Poly Haven families: our family <- its categories, how many
WEB = {"rock": (["rock"], 8), "concrete": (["concrete", "plaster-concrete"], 6), "brick": (["brick"], 6),
       "metal": (["metal"], 8), "ground": (["terrain"], 6), "gravel": (["gravel"], 5), "sand": (["sand"], 4),
       "wood": (["raw wood"], 4), "stone": (["cobblestone"], 5)}
CAN_MOSS = {"rock", "stone", "concrete", "brick", "ground", "gravel"}
# the families the ruin takes for rock, ground and debris (the destroy driver's lists): never a directional picture
ROCKISH = {"rock", "stone", "concrete", "gravel", "ground", "sand", "brick", "moss"}


# ---- the game's format -----------------------------------------------------------------------------------------
def pak_files(moddir: Path):
    for pak in sorted(moddir.glob("*.pak")):
        d = pak.read_bytes()
        if d[:4] != b"PACK":
            continue
        off, size = struct.unpack_from("<ii", d, 4)
        for i in range(size // 64):
            name, fo, fs = struct.unpack_from("<56sii", d, off + 64 * i)
            yield name.split(b"\0")[0].decode("latin1").lower(), d, fo, fs


def game_file(moddir: Path, name: str) -> bytes | None:
    loose = moddir / name
    if loose.is_file():
        return loose.read_bytes()
    for n, d, fo, fs in pak_files(moddir):
        if n == name.lower():
            return d[fo:fo + fs]
    return None


def palette(moddir: Path) -> list[int]:
    pcx = game_file(moddir, "pics/colormap.pcx")
    if not pcx:
        raise SystemExit(f"no pics/colormap.pcx in {moddir} or its paks: the game's palette is read from the game")
    return list(pcx[-768:])


def wal_bytes(im: Image.Image, pal: list[int], name: str) -> bytes:
    palimg = Image.new("P", (1, 1))
    palimg.putpalette(pal)
    w, h = im.size
    mips = [im.resize((max(1, w >> k), max(1, h >> k)), Image.LANCZOS)
            .quantize(palette=palimg, dither=Image.Dither.FLOYDSTEINBERG).tobytes() for k in range(4)]
    offs, at = [], 100
    for m in mips:
        offs.append(at)
        at += len(m)
    head = struct.pack("<32sII4I32sIII", name.encode("latin1")[:31], w, h, *offs, b"", 0, 0, 0)
    return head + b"".join(mips)


def wal_image(data: bytes, pal: list[int]) -> Image.Image:
    _, w, h = struct.unpack_from("<32sII", data, 0)
    off = struct.unpack_from("<I", data, 40)[0]
    im = Image.frombytes("P", (w, h), data[off:off + w * h])
    im.putpalette(pal)
    return im.convert("RGB")


# ---- making a picture a surface ------------------------------------------------------------------------------
def trim_bands(a: np.ndarray) -> tuple[np.ndarray, list[str]]:
    """Flat or foreign bands at the edges - a photobank's footer with its caption, a border, a frame - cut away: a
    run of edge rows (columns) whose mean colour stands off the body's by more than the body's own row-to-row spread."""
    said = []
    for side in range(4):
        b = np.rot90(a, side)
        rows = b.reshape(b.shape[0], -1, 3).mean(axis=1)
        body = np.median(rows[b.shape[0] // 5: -b.shape[0] // 5], axis=0)
        spread = np.percentile(np.abs(rows[b.shape[0] // 5: -b.shape[0] // 5] - body).sum(axis=1), 95) + 6.0
        n = 0
        while n < b.shape[0] // 4 and np.abs(rows[-1 - n] - body).sum() > spread:
            n += 1
        if n:
            n += max(2, b.shape[0] // 50)          # and a margin past the band's edge
            b = b[:-n]
            said.append(f"band {n}px")
        a = np.rot90(b, -side)
    return a, said


def flatten(im: Image.Image) -> Image.Image:
    """The light evened out: the picture over its own very blurred self, times its mean - a vignette or a lamp's
    gradient goes, the surface's own detail stays."""
    a = np.asarray(im).astype(np.float32)
    big = np.asarray(im.filter(ImageFilter.GaussianBlur(radius=im.size[0] / 5))).astype(np.float32) + 1.0
    out = a / big * a.reshape(-1, 3).mean(axis=0)
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))


def tileable(im: Image.Image, fade: float = 1 / 5) -> Image.Image:
    """Tileable: the picture shifted by half (its own middle then lies at the edges, continuous across the wrap)
    blended in near the edges over `fade` of the size; the middle is the picture itself."""
    a = np.asarray(im).astype(np.float32)
    n = a.shape[0]
    b = np.roll(np.roll(a, n // 2, 0), n // 2, 1)
    y, x = np.mgrid[0:n, 0:n].astype(np.float32)
    edge = np.minimum(np.minimum(x, n - 1 - x), np.minimum(y, n - 1 - y))
    w = np.clip(edge / (n * fade), 0, 1)[..., None]
    w = w * w * (3 - 2 * w)                                  # smooth step: no visible band where the blend ends
    return Image.fromarray(np.clip(a * w + b * (1 - w), 0, 255).astype(np.uint8))


def seam_score(im: Image.Image) -> float:
    """The step across the wrap over the step between neighbours inside: 1 is a seam no one sees."""
    a = np.asarray(im).astype(np.float32)
    inner = (np.abs(np.diff(a, axis=0)).mean() + np.abs(np.diff(a, axis=1)).mean()) / 2 + 1e-3
    wrap = (np.abs(a[0] - a[-1]).mean() + np.abs(a[:, 0] - a[:, -1]).mean()) / 2
    return float(wrap / inner)


def perspective(a: np.ndarray) -> float:
    """A floor shot at an angle has fine detail at the top and coarse at the bottom (or the reverse): the high
    frequency energy of the top third over the bottom third, the larger way round."""
    g = a.mean(axis=2)
    hf = np.abs(np.diff(g, axis=1))
    t, b = hf[: g.shape[0] // 3].mean() + 1e-3, hf[-g.shape[0] // 3:].mean() + 1e-3
    return float(max(t / b, b / t))


def hsv_mean(a: np.ndarray) -> tuple[float, float, float]:
    im = Image.fromarray(a.astype(np.uint8)).convert("HSV")
    h = np.asarray(im).reshape(-1, 3).astype(np.float32)
    ang = h[:, 0] / 255.0 * 2 * math.pi
    hue = (math.degrees(math.atan2(np.sin(ang).mean(), np.cos(ang).mean())) + 360) % 360
    return hue, float(h[:, 1].mean() / 255.0), float(h[:, 2].mean())


# a picture whose grain runs one way (slats, planks, a fluted or wavy panel, logs, bamboo) is never rock: brief 12 -
# the PO's slatted wall panel was called «stone» (dull, grainy) and dressed the debris in hard stripes (quake212..214).
# Measured over the pack of 07.10: every slat/plank/panel picture 0.64..0.99, every brick, stone, rock and ground
# 0.00..0.59 (brick courses run one way too, the most of them: 0.58)
DIRECTIONAL = 0.60


def coherence(a: np.ndarray) -> float:
    """How much the picture's grain runs one way: the structure tensor's coherence over the whole picture (0 no
    direction, 1 all edges one way), after a light blur so a pixel's noise does not count."""
    g = np.asarray(Image.fromarray(a.astype(np.uint8)).convert("L").filter(ImageFilter.GaussianBlur(1.0)))
    g = g.astype(np.float32)
    gx, gy = np.diff(g, axis=1)[:-1, :], np.diff(g, axis=0)[:, :-1]
    jxx, jyy, jxy = float((gx * gx).mean()), float((gy * gy).mean()), float((gx * gy).mean())
    tr, det = jxx + jyy, jxx * jyy - jxy * jxy
    root = math.sqrt(max(tr * tr / 4 - det, 0.0))
    return float(2 * root / (tr + 1e-6))


def classify(a: np.ndarray, where: str) -> tuple[str, str]:
    """The material by colour and grain, and why not when it is no Quake II surface."""
    hue, sat, val = hsv_mean(a)
    if coherence(a) >= DIRECTIONAL:
        # slats, planks, logs, panels: wood when warm, a panel otherwise - never stone, rock, concrete or ground
        return ("wood" if 15 <= hue < 60 and sat > 0.2 else "panel"), ""
    g = a.mean(axis=2)
    gx, gy = np.abs(np.diff(g, axis=1)).mean(), np.abs(np.diff(g, axis=0)).mean()
    grain = (gx + gy) / 2
    if sat > 0.22 and (180 <= hue <= 260):
        return "", "blue or turquoise - water, ice, paint: no surface of a Quake II level"
    if sat > 0.25 and (290 <= hue or hue < 8) and val > 140:
        return "", "pink - no surface of a Quake II level"
    if sat > 0.30 and 60 <= hue < 180:
        return "moss", ""
    if where == "wall":
        if sat > 0.30 and (hue < 30 or hue > 340) and val < 200:
            return "brick", ""
        if 15 <= hue < 50 and sat > 0.25 and max(gx, gy) > 1.8 * min(gx, gy):
            return "wood", ""
        return ("stone" if grain > 9 else "concrete"), ""
    if 25 <= hue < 60 and val > 150 and grain < 14:
        return "sand", ""
    if sat < 0.20 and grain > 10:
        return "gravel", ""
    if sat < 0.18:
        return "stone", ""
    return "ground", ""


def long(p: Path) -> Path:
    """A path past Windows' 260 characters, opened all the same (the PO's pictures keep their web names)."""
    s = str(p.resolve())
    return Path(s if s.startswith("\\\\?\\") or len(s) < 240 else "\\\\?\\" + s)


def surface(src: Path, where: str) -> tuple[Image.Image | None, dict]:
    src = long(src)
    info = {"source": str(src).replace("\\\\?\\", ""), "sha256": hashlib.sha256(src.read_bytes()).hexdigest()[:16]}
    if PHOTOBANK.search(src.name):
        return None, {**info, "status": "refused", "why": "a photobank's name: its picture carries its mark"}
    try:
        im = Image.open(src)
        im.load()
    except Exception as e:                                  # noqa: BLE001 - a broken download is refused, said
        return None, {**info, "status": "refused", "why": f"unreadable ({type(e).__name__})"}
    im = im.convert("RGB")
    if min(im.size) < 360:
        return None, {**info, "status": "refused", "why": f"too small ({im.size[0]}x{im.size[1]})"}
    if max(im.size) > 2048:
        im.thumbnail((2048, 2048), Image.LANCZOS)
    a, bands = trim_bands(np.asarray(im))
    if min(a.shape[:2]) < 300:
        return None, {**info, "status": "refused", "why": "the bands would not trim: too little surface left"}
    p = perspective(a)
    if p > 2.2:
        return None, {**info, "status": "refused", "why": f"a perspective shot (detail {p:.1f}x finer at one end)"}
    side = min(a.shape[:2])
    y0, x0 = (a.shape[0] - side) // 2, (a.shape[1] - side) // 2
    sq = Image.fromarray(a[y0:y0 + side, x0:x0 + side]).resize((HI, HI), Image.LANCZOS)
    sq = tileable(flatten(sq))
    s = seam_score(sq)
    if s > 2.5:
        return None, {**info, "status": "refused", "why": f"a seam stays ({s:.1f})"}
    arr = np.asarray(sq).astype(np.float32)
    mat, why = classify(arr, where)
    if not mat:
        return None, {**info, "status": "refused", "why": why}
    return sq, {**info, "material": mat, "seam": round(s, 2), "trimmed": bands, "coherence": round(coherence(arr), 3)}


# ---- generated masks ----------------------------------------------------------------------------------------
def crack_mask(seed: int, cells: int = 24, width: float = 2.5, size: int = WAL) -> np.ndarray:
    """Cracks: the edges of a jittered Voronoi tiling, broken (some edges dropped), on a torus so the mask tiles."""
    rng = np.random.default_rng(seed)
    pts = rng.random((cells, 2)) * size
    y, x = np.mgrid[0:size, 0:size].astype(np.float32)
    d = []
    for px, py in pts:
        dx = np.minimum(np.abs(x - px), size - np.abs(x - px))
        dy = np.minimum(np.abs(y - py), size - np.abs(y - py))
        d.append(np.hypot(dx, dy))
    d = np.sort(np.stack(d), axis=0)
    edge = np.clip(1.0 - (d[1] - d[0]) / width, 0, 1)
    # which edges stay: blotches of a noise that TILES (an 8x8 grid scaled up did not wrap - brief 12 found a seam
    # line across two of the three networks where the face repeats them)
    keep = np.clip((smooth_noise(size, seed + 7, waves=24, top=4) - 0.30) * 4.0, 0, 1)
    return np.clip(edge * keep * 1.4, 0, 1)


def crater_mask(seed: int, size: int = WAL) -> np.ndarray:
    """A crater from above: a dark bowl, a lighter rim, rays of thrown earth, ring noise."""
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:size, 0:size].astype(np.float32)
    r = np.hypot(x - size / 2, y - size / 2) / (size / 2)
    ang = np.arctan2(y - size / 2, x - size / 2)
    wob = 1 + 0.12 * np.sin(ang * rng.integers(5, 9) + rng.random() * 6) + 0.06 * np.sin(ang * 13)
    rr = r * wob
    bowl = np.clip(1 - rr / 0.55, 0, 1) ** 0.7
    rays = np.clip(1 - rr, 0, 1) * (0.5 + 0.5 * np.sin(ang * rng.integers(11, 19))) * 0.35
    return np.clip(bowl + rays, 0, 1)


def hole_mask(seed: int, size: int = WAL) -> np.ndarray:
    rng = np.random.default_rng(seed)
    m = np.zeros((size, size), np.float32)
    y, x = np.mgrid[0:size, 0:size].astype(np.float32)
    for _ in range(rng.integers(6, 14)):
        cx, cy, rad = rng.random() * size, rng.random() * size, 3 + rng.random() * 7
        r = np.hypot(np.minimum(np.abs(x - cx), size - np.abs(x - cx)), np.minimum(np.abs(y - cy), size - np.abs(y - cy)))
        m = np.maximum(m, np.clip(1 - (r - rad) / 4, 0, 1))
    return m


def dust_mask(seed: int, size: int = WAL) -> np.ndarray:
    """Dust and grime over a broken piece: fine blotches that TILE (12..20 cycles a picture - no blob the eye
    counts), never under half, so the piece is darker all over and uneven."""
    return 0.5 + 0.5 * smooth_noise(size, seed, waves=40, top=20)


def soot_mask(seed: int, size: int = WAL) -> np.ndarray:
    big = smooth_noise(size, seed, top=4)
    y, x = np.mgrid[0:size, 0:size].astype(np.float32)
    r = np.hypot(x - size / 2, y - size / 2) / (size / 2)
    return np.clip((1 - r) * 1.3 * (0.5 + big), 0, 1)


def picture_mask(path: Path, size: int = WAL) -> np.ndarray | None:
    """One of the PO's crater pictures as a mask: its alpha (or its darkness on a white ground), the white ground
    gone - no halo can reach the game."""
    try:
        im = Image.open(long(path))
        im.load()
    except Exception:                                          # noqa: BLE001
        return None
    if im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info):
        rgba = im.convert("RGBA")
        alpha = np.asarray(rgba.split()[3]).astype(np.float32) / 255
        dark = 1 - np.asarray(rgba.convert("L")).astype(np.float32) / 255
        m = alpha * np.clip(dark * 1.5, 0, 1)
    else:
        g = np.asarray(im.convert("L")).astype(np.float32) / 255
        m = np.clip((0.92 - g) / 0.6, 0, 1)                  # white ground -> 0
    m = np.asarray(ImageOps.fit(Image.fromarray((m * 255).astype(np.uint8)), (size, size), Image.LANCZOS)) / 255.0
    # the mask fades to nothing at its border: composited, no edge of it shows
    y, x = np.mgrid[0:size, 0:size].astype(np.float32)
    edge = np.clip(np.minimum(np.minimum(x, size - 1 - x), np.minimum(y, size - 1 - y)) / (size * 0.08), 0, 1)
    return m * edge


def masks() -> dict[str, np.ndarray]:
    out = {}
    for k in range(3):
        out[f"crack{k + 1}"] = crack_mask(101 + k, cells=16 + 8 * k, width=2.0 + k)
        # brief 12: three more networks, other cell counts and widths - a face's crack is one of six, never a stamp
        out[f"crack{k + 4}"] = crack_mask(111 + k, cells=12 + 12 * k, width=1.5 + k)
        out[f"dust{k + 1}"] = dust_mask(501 + k)
        out[f"crater{k + 1}"] = crater_mask(201 + k)
        out[f"hole{k + 1}"] = hole_mask(301 + k)
        out[f"soot{k + 1}"] = soot_mask(401 + k)
    for i, p in enumerate(sorted(CRATERS.glob("*"))):
        m = picture_mask(p)
        if m is not None and m.mean() > 0.01:
            out[f"po{i + 1:02d}"] = m
    return out


# ---- variants -----------------------------------------------------------------------------------------------
def smooth_noise(size: int, seed: int, waves: int = 24, top: int = 6) -> np.ndarray:
    """Smooth noise that TILES: a sum of waves of whole periods over the picture (1..top cycles), 0..1 - blotches,
    never squares, and no seam where the texture repeats."""
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:size, 0:size].astype(np.float32) * (2 * math.pi / size)
    acc = np.zeros((size, size), np.float32)
    for _ in range(waves):
        fx, fy = rng.integers(-top, top + 1), rng.integers(-top, top + 1)
        if fx == 0 and fy == 0:
            continue
        amp = 1.0 / math.hypot(fx, fy)
        acc += amp * np.sin(fx * x + fy * y + rng.random() * 2 * math.pi)
    acc -= acc.min()
    return acc / max(1e-6, acc.max())


def variant(im: Image.Image, kind: str, seed: int) -> Image.Image:
    a = np.asarray(im).astype(np.float32)
    lum = a.mean(axis=2, keepdims=True)
    # fine noise, 10..16 cycles a picture: a variant's blotches at a tile's period are a grid on a big floor
    # (brief 12, quake210: the soot variant's six big blotches a tile, repeated over a ruined floor)
    n = smooth_noise(im.size[0], seed, waves=40, top=16)[..., None]
    if kind == "dk":
        a = a * 0.62
    elif kind == "wet":
        m = a.mean()
        a = (a - m) * 1.25 + m * 0.7
    elif kind == "moss":
        hollow = np.clip((lum.mean() - lum) / 60 + 0.25, 0, 1) * np.clip(n * 1.6 - 0.3, 0, 1)
        a = a * (1 - 0.7 * hollow) + np.array([62, 86, 34], np.float32) * (lum / 140) * 0.7 * hollow
    elif kind == "rust":
        spot = np.clip(n * 1.8 - 0.55, 0, 1)
        a = a * (1 - 0.75 * spot) + np.array([120, 58, 26], np.float32) * (0.5 + lum / 255) * 0.75 * spot
    elif kind == "soot":
        a = a * (0.50 + 0.18 * n)
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def cracked(im: Image.Image, mask: np.ndarray, strength: float = 0.5) -> Image.Image:
    """A crack drawn into a texture: dark in the crack, a light lip on one side (light from above-left)."""
    w, h = im.size
    m = np.asarray(Image.fromarray((mask * 255).astype(np.uint8)).resize((w, h), Image.LANCZOS)).astype(np.float32) / 255
    lip = np.clip(np.roll(np.roll(m, -1, 0), -1, 1) - m, 0, 1)
    a = np.asarray(im).astype(np.float32)
    a = a * (1 - strength * m[..., None]) + 40 * lip[..., None]
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


# ---- the sources ----------------------------------------------------------------------------------------------
def fetch_web(sources: Path) -> list[tuple[Path, str]]:
    """Poly Haven's 1K colour maps by family, once each (kept in the sources folder)."""
    sources.mkdir(parents=True, exist_ok=True)
    got = []

    def get(url: str, timeout: int = 60) -> bytes:
        req = urllib.request.Request(url, headers={"User-Agent": "mapgen-textures"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()

    index_path = sources / "polyhaven_index.json"
    if not index_path.is_file():
        index_path.write_bytes(get("https://api.polyhaven.com/assets?t=textures"))
    index = json.loads(index_path.read_text(encoding="utf-8"))
    for fam, (cats, n) in WEB.items():
        ids = sorted(k for k, v in index.items() if set(cats) & set(v.get("categories", [])))
        for aid in ids[:n * 2]:
            if sum(1 for _, f in got if f == fam) >= n:
                break
            path = sources / f"ph_{fam}_{aid}.jpg"
            if not path.is_file():
                try:
                    files = json.loads(get(f"https://api.polyhaven.com/files/{aid}"))
                    url = files["Diffuse"]["1k"]["jpg"]["url"]
                    path.write_bytes(get(url, 300))
                except Exception as e:                       # noqa: BLE001 - said, the rest go on
                    print(f"  fetch {aid}: {type(e).__name__}", flush=True)
                    continue
            got.append((path, fam))
    return got


def build(out: Path, fetch: bool, moddir: Path, only: list | None = None, sheets_to: Path | None = None,
          catalogue_to: Path | None = CATALOGUE_COPY) -> int:
    """The pack from every source (or `only`, a guard's fixture: (path, "floor"|"wall"|"web", family or None))."""
    pal = palette(moddir)
    tex = out / "textures" / "mapgen"
    if tex.exists():
        shutil.rmtree(tex)
    (tex / "masks").mkdir(parents=True)
    struck = set(json.loads(REFUSED_BY_EYE.read_text(encoding="utf-8")).get("refused", [])) \
        if REFUSED_BY_EYE.is_file() else set()
    cat = {"palette": "pics/colormap.pcx of " + str(moddir), "wal": WAL, "hi": HI, "textures": [], "masks": [],
           "refused": []}
    fams: dict[str, list] = {}
    todo = [(p, "floor", None) for p in sorted((SURFACES / "Поверхности для пола").glob("*"))] \
        + [(p, "wall", None) for p in sorted((SURFACES / "Поверхности для стен").glob("*"))]
    if fetch and only is None:
        todo += [(p, "web", fam) for p, fam in fetch_web(SOURCES)]
    if only is not None:
        todo = only
    for src, where, fam in todo:
        im, info = surface(src, "wall" if where == "wall" else "floor")
        if im is not None and fam:
            info["material"] = fam                     # the source's own family, not a guess
            if fam in ROCKISH and info["coherence"] >= DIRECTIONAL:
                info["material"] = "panel"             # a family's picture with a grain one way: no rock
        if im is None:
            cat["refused"].append(info)
            continue
        fams.setdefault(info["material"], []).append((im, info))
    # per family the PER_FAMILY with the least seam, each with its variants
    for mat in sorted(fams):
        items = sorted(fams[mat], key=lambda t: t[1]["seam"])
        for k, (im, info) in enumerate(items):
            base = f"{mat}{k + 1:02d}"
            if k >= PER_FAMILY:
                cat["refused"].append({**info, "status": "spare", "why": f"the family {mat} has its {PER_FAMILY}"})
                continue
            if base in struck:
                cat["refused"].append({**info, "status": "refused", "why": "struck on the contact sheet"})
                continue
            kinds = ["", "dk", "wet", "soot"] + (["rust"] if mat == "metal" else ["moss"] if mat in CAN_MOSS else [])
            for v in kinds:
                name = base + (f"_{v}" if v else "")
                if name in struck:
                    continue
                pic = variant(im, v, zlib.crc32(name.encode())) if v else im
                (tex / f"{name}.wal").write_bytes(wal_bytes(pic.resize((WAL, WAL), Image.LANCZOS), pal,
                                                            f"mapgen/{name}"))
                pic.save(tex / f"{name}.jpg", quality=88)
                a = np.asarray(pic).astype(np.float32)
                cat["textures"].append({
                    "name": f"mapgen/{name}", "base": base, "variant": v or "base", "material": mat,
                    "kind": "ground" if mat in ("ground", "gravel", "sand", "moss") else "wall",
                    "rgb": [round(float(c), 1) for c in a.reshape(-1, 3).mean(axis=0)],
                    "lum": round(float(a.mean()), 1), "seam": info["seam"], "source": info["source"],
                    "coherence": info.get("coherence", 0.0),
                    "sha256": info["sha256"], "status": "accepted"})
    for name, m in masks().items():
        Image.fromarray((m * 255).astype(np.uint8)).save(tex / "masks" / f"{name}.png")
        # and as raw bytes, 256 x 256: the destroy driver draws the cracks itself (no numpy, no Pillow at the user's)
        (tex / "masks" / f"{name}.raw").write_bytes((m * 255).astype(np.uint8).tobytes())
        cat["masks"].append({"name": name, "kind": re.sub(r"\d+$", "", name).replace("po", "picture"),
                             "cover": round(float(m.mean()), 3)})
    (tex / "catalogue.json").write_text(json.dumps(cat, indent=1, ensure_ascii=False), encoding="utf-8")
    if catalogue_to:
        catalogue_to.write_text(json.dumps(cat, indent=1, ensure_ascii=False), encoding="utf-8")
    sheets(tex, cat, sheets_to or SHEETS)
    acc = len(cat["textures"])
    print(json.dumps({"accepted": acc, "bases": len({t["base"] for t in cat["textures"]}),
                      "families": {m: len({t["base"] for t in cat["textures"] if t["material"] == m})
                                   for m in sorted(fams)},
                      "refused": len([r for r in cat["refused"] if r.get("status") == "refused"]),
                      "masks": len(cat["masks"]), "mb": round(sum(p.stat().st_size for p in tex.rglob("*")) / 2**20, 1)},
                     ensure_ascii=False))
    return 0


def sheets(tex: Path, cat: dict, to: Path) -> None:
    """One contact sheet a family: every accepted texture tiled 2x2, named - the PO strikes what he does not want."""
    to.mkdir(parents=True, exist_ok=True)
    by = {}
    for t in cat["textures"]:
        by.setdefault(t["material"], []).append(t)
    T = 200
    for mat, ts in by.items():
        cols = 5
        rows = (len(ts) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * T, rows * (T + 16)), (24, 24, 24))
        dr = ImageDraw.Draw(sheet)
        for i, t in enumerate(ts):
            im = Image.open(tex / (t["name"].split("/", 1)[1] + ".jpg")).resize((T // 2, T // 2))
            tile = Image.new("RGB", (T, T))
            for dx in (0, T // 2):
                for dy in (0, T // 2):
                    tile.paste(im, (dx, dy))
            x, y = (i % cols) * T, (i // cols) * (T + 16)
            sheet.paste(tile, (x, y + 16))
            dr.text((x + 3, y + 2), t["name"].split("/", 1)[1], fill=(255, 220, 120))
        sheet.save(to / f"{mat}.jpg", quality=85)
    masks_sheet = Image.new("RGB", (8 * 128, ((len(cat["masks"]) + 7) // 8) * 144), (24, 24, 24))
    dr = ImageDraw.Draw(masks_sheet)
    for i, m in enumerate(cat["masks"]):
        im = Image.open(tex / "masks" / f"{m['name']}.png").resize((128, 128))
        x, y = (i % 8) * 128, (i // 8) * 144
        masks_sheet.paste(ImageOps.invert(im.convert("RGB")), (x, y + 16))
        dr.text((x + 3, y + 2), m["name"], fill=(255, 220, 120))
    masks_sheet.save(to / "masks.jpg", quality=85)


# ---- into a game, and a map's own cracked textures ---------------------------------------------------------------
def install(moddir: Path, pack: Path) -> int:
    src = pack / "textures" / "mapgen"
    if not (src / "catalogue.json").is_file():
        raise SystemExit(f"no pack at {src}: build it first")
    dst = moddir / "textures" / "mapgen"
    dst.mkdir(parents=True, exist_ok=True)
    n = 0
    for p in src.rglob("*"):
        if p.is_file():
            q = dst / p.relative_to(src)
            q.parent.mkdir(parents=True, exist_ok=True)
            if not q.is_file() or q.stat().st_size != p.stat().st_size:
                shutil.copy2(p, q)
                n += 1
    print(f"installed {n} files of the pack into {dst}")
    return 0


def crack(moddir: Path, needs: Path, pack: Path, read_from: Path | None = None) -> int:
    """NEEDS: one line a variant, `NEW ORIGINAL MASK [REP]` (a texture name, a texture name, a mask of the pack, the
    original tiled REP x REP under it - a placed patch's picture). Each is
    the original's own .wal - loose or in a pak of MODDIR - with the mask drawn in, same size, same palette, written
    to MODDIR/textures/NEW.wal. The map then wears its own textures, cracked."""
    src = read_from or moddir
    pal = palette(src)
    mdir = pack / "textures" / "mapgen" / "masks"
    made = missing = 0
    for line in needs.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) not in (3, 4):
            continue
        new, orig, mask = parts[:3]
        rep = int(parts[3]) if len(parts) == 4 else 1
        data = game_file(moddir, f"textures/{orig}.wal") or game_file(src, f"textures/{orig}.wal")
        mp = mdir / f"{mask}.png"
        if not data or not mp.is_file():
            missing += 1
            continue
        m = np.asarray(Image.open(mp).convert("L")).astype(np.float32) / 255
        im = wal_image(data, pal)
        if rep > 1:
            tiled = Image.new("RGB", (im.size[0] * rep, im.size[1] * rep))
            for i in range(rep):
                for j in range(rep):
                    tiled.paste(im, (i * im.size[0], j * im.size[1]))
            im = tiled
        out = moddir / "textures" / f"{new}.wal"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(wal_bytes(cracked(im, m), pal, new))
        made += 1
    print(f"cracked variants: {made} made, {missing} without an original or a mask")
    return 0 if not missing else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["build", "install", "crack"])
    ap.add_argument("moddir", nargs="?", type=Path)
    ap.add_argument("needs", nargs="?", type=Path)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--pack", type=Path, default=OUT)
    ap.add_argument("--game", type=Path, default=GAME, help="the game whose palette the pack is drawn in")
    ap.add_argument("--no-fetch", action="store_true")
    a = ap.parse_args()
    if a.what == "build":
        return build(a.out, not a.no_fetch, a.game)
    if a.what == "install":
        return install(a.moddir, a.pack)
    return crack(a.moddir, a.needs, a.pack)


if __name__ == "__main__":
    sys.exit(main())
