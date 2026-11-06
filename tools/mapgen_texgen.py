r"""The Studio's own textures for a map from scratch (the PO, 05.11: «нужен подраздел генерации текстур карт с нуля самой
студией - раздобудь из интернета какой-нибудь бесплатный генератор на гитхабе и адаптируй под нас, пусть генерирует
текстуры, когда такое разрешено в настройках, и параметры для этого задай»).

The noise is Procedural-PBR's (Whappens, MIT - `mapgen_texgen_noise.py`, the licence in tools/third_party); the
materials are Quake II's: riveted metal panels, gratings, floor tiles, brick (Procedural-PBR's recipe), stone blocks,
concrete, rock, trims with rivets or hazard stripes. Each is a height field and a colour field, the relief baked into
the colour by a light from the upper left (Quake II's textures carry their own shading - the game has no normal maps),
tileable on every edge, as dark and as coloured as people's textures (their brightness 20..42, coloured 50..100 %,
tools/mapgen_people_style.json) unless asked otherwise.

A set: a theme (tech, gothic, industrial, base), a colour, wear, the size of the detail, the relief - by role: four
walls, three floors, three ceilings, four details (trims, posts, frames, risers), a tread. Written into the game as
`textures/mapgen_gen/<set>/<name>.wal` (256, the game's palette, four mips) and `.jpg` (512, what q2pro draws).

    python tools/mapgen_texgen.py OUT_DIR [--theme tech] [--colour warm] [--wear worn] [--scale medium]
                                          [--relief medium] [--seed 7] [--game DIR]     # a set + a contact sheet
"""
from __future__ import annotations

import argparse
import colorsys
import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import mapgen_texgen_noise as nz  # noqa: E402

SIZE = 512
# a set's folder is made once per its key: a change in how the materials are painted bumps this, so a client keeps no
# stale set under a new Studio (the key holds it)
VERSION = 4
THEMES = ("tech", "gothic", "industrial", "base", "snow", "forest", "city", "planet", "fantasy", "desert", "hell")
COLOURS = ("auto", "warm", "cold", "green", "rust", "grey")
WEARS = ("clean", "worn", "dirty")
SCALES = ("small", "medium", "large")
RELIEFS = ("soft", "medium", "sharp")

# which material each role takes, by theme (several, the set's seed picks among them)
RECIPES = {
    "tech": {"wall": ["panel", "panel", "rivets", "grate"], "floor": ["tiles", "panel", "concrete"],
             "ceil": ["panel", "grate", "rivets"], "detail": ["trim_rivets", "trim_bands", "rivets", "trim_hazard"]},
    "gothic": {"wall": ["stone", "brick", "stone", "rock"], "floor": ["stone", "tiles", "rock"],
               "ceil": ["rock", "stone", "brick"], "detail": ["trim_bands", "stone", "trim_rivets", "brick"]},
    "industrial": {"wall": ["rivets", "concrete", "panel", "grate"], "floor": ["concrete", "tiles", "panel"],
                   "ceil": ["concrete", "grate", "panel"], "detail": ["trim_hazard", "trim_rivets", "rivets", "trim_bands"]},
    "base": {"wall": ["concrete", "panel", "tiles", "brick"], "floor": ["tiles", "concrete", "panel"],
             "ceil": ["concrete", "panel", "tiles"], "detail": ["trim_bands", "trim_rivets", "panel", "trim_hazard"]},
    # 3.46 (the PO 05.11: «снежные поверхности, лес, город, планеты, фэнтези и так далее»)
    "snow": {"wall": ["snowstone", "ice", "rock", "planks"], "floor": ["snow", "ice", "snow"],
             "ceil": ["rock", "ice", "snowstone"], "detail": ["planks", "ice", "trim_bands", "trim_rivets"]},
    "forest": {"wall": ["bark", "planks", "mossstone", "planks"], "floor": ["moss", "planks", "cobble"],
               "ceil": ["planks", "bark", "rock"], "detail": ["planks", "bark", "trim_bands", "moss"]},
    "city": {"wall": ["facade", "brick", "concrete", "panel"], "floor": ["asphalt", "tiles", "concrete"],
             "ceil": ["concrete", "panel", "tiles"], "detail": ["markings", "trim_hazard", "trim_rivets", "brick"]},
    "planet": {"wall": ["crater", "crystal", "alien", "panel"], "floor": ["crater", "rock", "alien"],
               "ceil": ["rock", "crystal", "crater"], "detail": ["crystal", "trim_rivets", "alien", "trim_bands"]},
    "fantasy": {"wall": ["stone", "cobble", "planks", "brick"], "floor": ["cobble", "planks", "tiles"],
                "ceil": ["planks", "stone", "rock"], "detail": ["runes", "gold", "planks", "trim_bands"]},
    "desert": {"wall": ["sandstone", "sand", "stone", "tiles"], "floor": ["sand", "tiles", "sandstone"],
               "ceil": ["sandstone", "rock", "stone"], "detail": ["runes", "trim_bands", "gold", "sandstone"]},
    "hell": {"wall": ["lavarock", "rock", "brick", "stone"], "floor": ["lavarock", "rock", "grate"],
             "ceil": ["rock", "lavarock", "stone"], "detail": ["runes", "trim_rivets", "lavarock", "gold"]},
}
# a theme's own colours for «auto» (hue, saturation, value): its world's, not the generic warm/cold
THEME_HUES = {
    "snow": [(0.58, 0.16, 0.58), (0.55, 0.22, 0.52), (0.60, 0.10, 0.50)],
    "forest": [(0.08, 0.55, 0.36), (0.27, 0.50, 0.32), (0.10, 0.45, 0.30)],
    "city": [(0.60, 0.14, 0.38), (0.05, 0.40, 0.36), (0.12, 0.20, 0.34)],
    "planet": [(0.78, 0.50, 0.38), (0.48, 0.55, 0.36), (0.90, 0.45, 0.36)],
    "fantasy": [(0.09, 0.40, 0.40), (0.07, 0.30, 0.36), (0.12, 0.55, 0.38)],
    "desert": [(0.09, 0.55, 0.46), (0.07, 0.50, 0.42), (0.10, 0.40, 0.44)],
    "hell": [(0.00, 0.72, 0.34), (0.03, 0.65, 0.32), (0.98, 0.55, 0.28)],
}
# the lamps' tint of a theme's set (its colour «auto»)
THEME_LIGHT = {"snow": (0.78, 0.88, 1.0), "forest": (0.88, 1.0, 0.78), "city": (1.0, 0.92, 0.80),
               "planet": (0.86, 0.74, 1.0), "fantasy": (1.0, 0.84, 0.62), "desert": (1.0, 0.88, 0.68),
               "hell": (1.0, 0.58, 0.42)}
# a theme's treads (the steps' tops)
THEME_TREAD = {"snow": "planks", "forest": "planks", "city": "markings", "planet": "grate", "fantasy": "planks",
               "desert": "sandstone", "hell": "grate"}
# the hue (0..1), saturation and value a colour asks for; «auto» - by the set's seed among the others
# 3.45 covers (05.11): the PO's client draws textures at gl_saturation 0.4 - a cold set at 0.35 came out grey and the
# hazard stripes near white; people's maps keep their colour through it. Set as strong as theirs read there
HUES = {"warm": (0.07, 0.62), "cold": (0.58, 0.58), "green": (0.30, 0.55), "rust": (0.04, 0.72), "grey": (0.10, 0.2)}


# ---- small helpers ---------------------------------------------------------------------------------------------
def _rng(seed: int, tag: str) -> np.random.Generator:
    h = int(hashlib.sha256(f"{seed}:{tag}".encode()).hexdigest()[:8], 16)
    return np.random.default_rng(h)


def _nseed(seed: int, tag: str) -> int:
    return int(hashlib.sha256(f"{seed}:{tag}:n".encode()).hexdigest()[:7], 16)


def _grid(size, cols, rows):
    yv, xv = np.indices((size, size), dtype=np.float32)
    cw, ch = size / cols, size / rows
    return xv, yv, cw, ch


def _bake(colour01: np.ndarray, height01: np.ndarray, relief: float) -> np.ndarray:
    """The relief lit from the upper left, as Quake II's textures carry it: a lambert term of the height's normal
    (tileable gradients) times the colour, plus a little cavity darkening."""
    hx, hy = nz.sobel_gradients(height01.astype(np.float64))
    k = 6.0 * relief
    nx, ny, nzv = -hx * k, -hy * k, np.ones_like(hx)
    norm = np.sqrt(nx * nx + ny * ny + nzv * nzv)
    lx, ly, lz = -0.55, -0.55, 0.63
    lam = np.clip((nx * lx + ny * ly + nzv * lz) / norm, 0.0, 1.0)
    shade = 0.45 + 0.75 * lam
    cavity = 0.75 + 0.25 * nz.normalize01(nz.tileable_gaussian_blur(height01, 3))
    return np.clip(colour01 * (shade * cavity)[..., None], 0.0, 1.0)


def _tint(base_rgb, field01, spread=0.25):
    """A colour over a 0..1 field: darker in the lows, lighter in the highs."""
    b = np.array(base_rgb, dtype=np.float32)
    t = (0.75 + spread * 2 * (field01 - 0.5))[..., None]
    return np.clip(b[None, None, :] * t, 0, 1)


def _metal(size, seed, tag):
    """Metal's surface: soft mottling plus fine brushed streaks (not the long blobs that read as wood)."""
    mott = nz.normalize01(nz.fbm_perlin(size, 8, octaves=4, seed=_nseed(seed, tag + "m")))
    fine = nz.normalize01(nz.generate_perlin_noise_2d(size, (256, 16), seed=_nseed(seed, tag + "f")))
    return nz.normalize01(0.8 * mott + 0.2 * fine)


def _wear_maps(size, seed, wear):
    """Grime in the hollows and streaks running down; rust patches on «dirty»."""
    amount = {"clean": 0.15, "worn": 0.45, "dirty": 0.8}[wear]
    grime = nz.normalize01(nz.fbm_perlin(size, 6, octaves=4, seed=_nseed(seed, "grime")))
    streak = nz.normalize01(nz.generate_perlin_noise_2d(size, (12, 2), seed=_nseed(seed, "streak")))
    grime = np.clip((grime - (1 - amount * 0.7)) * 3, 0, 1)
    streak = np.clip((streak - (1 - amount * 0.5)) * 2.5, 0, 1)
    rust = np.clip((nz.normalize01(nz.fbm_perlin(size, 8, octaves=3, seed=_nseed(seed, "rust"))) - (1.0 - 0.25 * amount)) * 4, 0, 1)
    return grime, streak, rust * (1 if wear == "dirty" else 0.35 if wear == "worn" else 0)


# ---- materials: each returns (height 0..1, colour 0..1 HxWx3) ---------------------------------------------------
def m_panel(size, seed, rgb, scale):
    cols = {"small": 4, "medium": 2, "large": 1}[scale] * 2
    rows = cols if seed % 2 else max(1, cols // 2)
    xv, yv, cw, ch = _grid(size, cols, rows)
    lx, ly = xv % cw, yv % ch
    gap = max(3, size // 128)
    ex = np.minimum(lx, cw - lx)
    ey = np.minimum(ly, ch - ly)
    edge = np.minimum(ex, ey)
    groove = edge < gap
    bevel = np.clip((edge - gap) / (gap * 3), 0, 1)
    rng = _rng(seed, "panel")
    shade = rng.uniform(-0.12, 0.12, (cols, rows)).astype(np.float32)
    pid = shade[(xv // cw).astype(int) % cols, (yv // ch).astype(int) % rows]
    grain = _metal(size, seed, "brush")
    h = np.where(groove, 0.1, 0.35 + 0.45 * bevel) + (grain - 0.5) * 0.05
    # rivets near the corners of each panel
    r = max(3, size // 96)
    for fx, fy in ((0.12, 0.12), (0.88, 0.12), (0.12, 0.88), (0.88, 0.88)):
        d = np.hypot(lx - cw * fx, ly - ch * fy)
        h = np.where(d < r, 0.9 - (d / r) * 0.3, h)
    col = _tint(rgb, grain, 0.18) * (1 + pid[..., None])
    col = np.where(groove[..., None], col * 0.45, col)
    return nz.normalize01(h), col


def m_rivets(size, seed, rgb, scale):
    step = {"small": 32, "medium": 48, "large": 64}[scale] * size // 512
    h, col = m_panel(size, seed + 1, rgb, "large")
    yv, xv = np.indices((size, size), dtype=np.float32)
    lx, ly = xv % step, yv % step
    d = np.hypot(lx - step / 2, ly - step / 2)
    r = max(3, step // 7)
    riv = d < r
    h = np.where(riv, 0.95 - (d / r) * 0.25, h * 0.8)
    plate = nz.normalize01(nz.fbm_perlin(size, 16, octaves=3, seed=_nseed(seed, "plate")))
    col = col * (0.85 + 0.3 * plate[..., None])
    return nz.normalize01(h), col


def m_grate(size, seed, rgb, scale):
    cells = {"small": 16, "medium": 10, "large": 6}[scale]
    xv, yv, cw, ch = _grid(size, cells, cells)
    lx, ly = xv % cw, yv % ch
    bar = max(3, int(cw * 0.22))
    holes = (lx > bar) & (ly > bar)
    h = np.where(holes, 0.0, 0.85)
    edge = np.minimum(np.minimum(lx, ly), bar)
    h = np.where(holes, 0.0, 0.55 + 0.4 * np.clip(edge / bar, 0, 1))
    under = nz.normalize01(nz.fbm_perlin(size, 8, octaves=3, seed=_nseed(seed, "under")))
    col = _tint(rgb, under, 0.2)
    col = np.where(holes[..., None], col * 0.3, col)
    return nz.normalize01(h), col


def m_tiles(size, seed, rgb, scale):
    n = {"small": 8, "medium": 4, "large": 2}[scale]
    xv, yv, cw, ch = _grid(size, n, n)
    lx, ly = xv % cw, yv % ch
    grout = max(3, size // 96)
    g = (lx < grout) | (ly < grout)
    rng = _rng(seed, "tiles")
    shade = rng.uniform(-0.18, 0.18, (n, n)).astype(np.float32)
    tid = shade[(xv // cw).astype(int) % n, (yv // ch).astype(int) % n]
    edge = np.minimum(np.minimum(lx - grout, ly - grout), np.minimum(cw - lx, ch - ly))
    bevel = np.clip(edge / (grout * 2), 0, 1)
    speck = nz.normalize01(nz.fbm_perlin(size, 32, octaves=3, seed=_nseed(seed, "speck")))
    h = np.where(g, 0.05, 0.5 + 0.4 * bevel) + (speck - 0.5) * 0.04
    col = _tint(rgb, speck, 0.2) * (1 + tid[..., None])
    col = np.where(g[..., None], col * 0.35, col)
    # diamond plate on every other tile of a tech floor (seed odd)
    if seed % 3 == 0:
        yy, xx = np.indices((size, size), dtype=np.float32)
        p = size / (n * 6)
        dia = (np.abs(((xx + yy) % (2 * p)) - p) < p * 0.18) & (np.abs(((xx - yy) % (2 * p)) - p) > p * 0.6)
        h = np.where(dia & ~g, h + 0.25, h)
    return nz.normalize01(h), col


def m_brick(size, seed, rgb, scale):
    """Procedural-PBR's brick (rows of half-offset bricks, recessed mortar, bevel, per-brick shade, chipped corners),
    on our colours."""
    rows = {"small": 16, "medium": 12, "large": 8}[scale]
    cols = rows // 2 + (rows // 2) % 2
    yv, xv = np.indices((size, size), dtype=np.float32)
    bw, bh = size / cols, size / rows
    row = (yv // bh).astype(np.int32)
    off = np.where(row % 2 == 1, bw / 2, 0)
    xs = (xv + off) % size
    col_i = (xs // bw).astype(np.int32) % cols
    lx, ly = xs % bw, yv % bh
    mortar = max(2, size // 128)
    warp = nz.generate_perlin_noise_2d(size, 8, seed=_nseed(seed, "warp")) * mortar * 0.7
    mloc = np.clip(mortar + warp, 1, mortar * 2)
    mm = (lx < mloc) | (lx > bw - mloc) | (ly < mloc) | (ly > bh - mloc)
    edge = np.minimum(np.minimum(lx, bw - lx), np.minimum(ly, bh - ly))
    bevel = np.clip(edge / (mortar * 1.6), 0, 1)
    rng = _rng(seed, "brick")
    shade = rng.uniform(-1, 1, rows * cols).astype(np.float32)[(row % rows) * cols + col_i]
    fine = nz.normalize01(nz.fbm_perlin(size, 32, octaves=3, seed=_nseed(seed, "fine")))
    h = np.where(mm, 0.22, 0.22 + 0.6 * bevel) + (fine - 0.5) * 0.06
    chip = nz.normalize01(nz.generate_perlin_noise_2d(size, rows * 2, seed=_nseed(seed, "chip")))
    h = h - ((~mm) & (edge < mortar * 3) & (chip > 0.8)) * 0.18
    col = _tint(rgb, fine, 0.2) * (1 + 0.12 * shade[..., None])
    col = np.where(mm[..., None], col * 0.4 + 0.05, col)
    return nz.normalize01(h), col


def m_stone(size, seed, rgb, scale):
    cells = {"small": 10, "medium": 6, "large": 4}[scale]
    f1, f2 = nz.generate_voronoi_f1_f2(size, cells, _nseed(seed, "stone"), warp_strength=0.15)
    edge = nz.normalize01(f2 - f1)
    joint = edge < 0.06
    bevel = np.clip(edge / 0.25, 0, 1)
    rough = nz.normalize01(nz.fbm_perlin(size, 24, octaves=4, seed=_nseed(seed, "rough")))
    h = np.where(joint, 0.05, 0.3 + 0.5 * bevel) + (rough - 0.5) * 0.15
    col = _tint(rgb, rough, 0.3) * (0.85 + 0.3 * nz.normalize01(f1)[..., None])
    col = np.where(joint[..., None], col * 0.35, col)
    return nz.normalize01(h), col


def m_concrete(size, seed, rgb, scale):
    base = nz.normalize01(nz.fbm_perlin(size, 6, octaves=5, seed=_nseed(seed, "conc")))
    pits = nz.normalize01(nz.fbm_perlin(size, 64, octaves=2, seed=_nseed(seed, "pits")))
    cracks = nz.voronoi_edge_lines(size, {"small": 8, "medium": 5, "large": 3}[scale], _nseed(seed, "crack"), 0.3, 18)
    n = {"small": 4, "medium": 2, "large": 1}[scale]
    yv, xv = np.indices((size, size), dtype=np.float32)
    seam = ((yv % (size / n)) < 3) | ((xv % (size / n)) < 3)
    h = 0.5 + (base - 0.5) * 0.3 - (pits > 0.85) * 0.2 - cracks * 0.25 - seam * 0.3
    col = _tint(rgb, base, 0.3) * (1 - 0.4 * cracks[..., None])
    return nz.normalize01(h), col


def m_rock(size, seed, rgb, scale):
    f = nz.normalize01(nz.fbm_perlin(size, {"small": 10, "medium": 6, "large": 4}[scale], octaves=6, seed=_nseed(seed, "rock")))
    ridges = nz.sharpen_crests(f, 1.5)
    cracks = nz.voronoi_edge_lines(size, 6, _nseed(seed, "rc"), 0.5, 10)
    h = 0.8 * f + 0.2 * ridges - cracks * 0.3
    col = _tint(rgb, nz.normalize01(h), 0.35)
    return nz.normalize01(h), col


def _trim(size, seed, rgb, kind):
    yv, xv = np.indices((size, size), dtype=np.float32)
    bands = 4
    bh = size / bands
    ly = yv % bh
    edge = np.minimum(ly, bh - ly)
    h = np.clip(edge / (bh * 0.2), 0, 1) * 0.6 + 0.2
    grain = _metal(size, seed, "tgrain")
    col = _tint(rgb, grain, 0.15)
    if kind == "trim_rivets":
        step = size / 16
        d = np.hypot((xv % step) - step / 2, ly - bh / 2)
        r = max(3, int(step / 6))
        h = np.where(d < r, 0.95 - d / r * 0.2, h)
    elif kind == "trim_hazard":
        stripe = (((xv + yv) // (size / 16)) % 2) == 0
        mid = (ly > bh * 0.25) & (ly < bh * 0.75)
        haz = np.where(stripe[..., None], np.array([0.62, 0.40, 0.02]), np.array([0.06, 0.06, 0.05]))
        col = np.where((mid[..., None]), haz * (0.75 + 0.25 * grain[..., None]), col)
    return nz.normalize01(h), col


# ---- 3.46: the new themes' materials ---------------------------------------------------------------------------
def _wrap_disc(size, cx, cy, r):
    """Distance to a centre on a torus (tileable craters, stones)."""
    yv, xv = np.indices((size, size), dtype=np.float32)
    dx = np.abs(xv - cx)
    dy = np.abs(yv - cy)
    dx = np.minimum(dx, size - dx)
    dy = np.minimum(dy, size - dy)
    return np.hypot(dx, dy) / r


def m_snow(size, seed, rgb, scale):
    drift = nz.normalize01(nz.fbm_perlin(size, {"small": 8, "medium": 5, "large": 3}[scale], octaves=5, seed=_nseed(seed, "drift")))
    wind = nz.normalize01(nz.generate_perlin_noise_2d(size, (24, 6), seed=_nseed(seed, "wind")))
    h = 0.75 * drift + 0.25 * wind
    rng = _rng(seed, "spark")
    col = _tint(rgb, h, 0.35)
    # shadows in the hollows turn blue, the crests white
    blue = np.array([0.55, 0.65, 0.85]) * (0.6 + 0.4 * np.mean(rgb))
    col = col * (0.75 + 0.25 * h[..., None]) + blue[None, None, :] * (1 - h[..., None]) * 0.15
    spark = rng.random((size, size)) > 0.9985
    col = np.where(spark[..., None], np.clip(col * 1.6, 0, 1), col)
    return nz.normalize01(h), col


def m_ice(size, seed, rgb, scale):
    cells = {"small": 10, "medium": 6, "large": 4}[scale]
    f1, f2 = nz.generate_voronoi_f1_f2(size, cells, _nseed(seed, "ice"), warp_strength=0.2)
    edge = nz.normalize01(f2 - f1)
    crack = edge < 0.05
    depth = nz.normalize01(nz.fbm_perlin(size, 6, octaves=4, seed=_nseed(seed, "deep")))
    h = 0.5 + 0.3 * nz.normalize01(f1) * 0.5 - crack * 0.3
    ice = np.array(rgb) * np.array([0.8, 1.0, 1.25])
    col = np.clip(ice[None, None, :] * (0.7 + 0.5 * depth[..., None]), 0, 1)
    col = np.where(crack[..., None], np.clip(col * 1.5 + 0.08, 0, 1), col)
    return nz.normalize01(h), col


def m_snowstone(size, seed, rgb, scale):
    """Stone blocks with snow lying on their tops."""
    h, col = m_stone(size, seed, (0.32, 0.33, 0.36), scale)
    cap = nz.normalize01(nz.fbm_perlin(size, 8, octaves=3, seed=_nseed(seed, "cap")))
    gy = np.roll(h, 3, axis=0) - h               # a top edge: the stone rises below it
    snow_on = np.clip((gy * 6 + cap - 0.6) * 3, 0, 1) * (h > 0.25)
    white = np.array(rgb) * 1.5 + 0.08
    col = col * (1 - snow_on[..., None]) + np.clip(white, 0, 1)[None, None, :] * snow_on[..., None]
    return nz.normalize01(h + snow_on * 0.1), col


def m_bark(size, seed, rgb, scale):
    streak = nz.normalize01(nz.generate_perlin_noise_2d(size, (6, 48), seed=_nseed(seed, "bark")))
    ridge = nz.sharpen_crests(streak, 2.0)
    fine = nz.normalize01(nz.fbm_perlin(size, 32, octaves=3, seed=_nseed(seed, "bfine")))
    h = 0.6 * ridge + 0.3 * streak + 0.1 * fine
    col = _tint(rgb, h, 0.45)
    return nz.normalize01(h), col


def m_moss(size, seed, rgb, scale):
    ground = nz.normalize01(nz.fbm_perlin(size, {"small": 12, "medium": 8, "large": 5}[scale], octaves=5, seed=_nseed(seed, "mg")))
    patch = nz.normalize01(nz.fbm_perlin(size, 4, octaves=3, seed=_nseed(seed, "mp")))
    moss = np.clip((patch - 0.45) * 4, 0, 1)
    soil = np.array(rgb) * np.array([1.0, 0.85, 0.7])
    green = np.array([0.16, 0.30, 0.08]) * (0.8 + 0.6 * np.mean(rgb))
    col = (soil[None, None, :] * (1 - moss[..., None]) + green[None, None, :] * moss[..., None]) * (0.7 + 0.5 * ground[..., None])
    rng = _rng(seed, "leaf")
    leaves = rng.random((size, size)) > 0.996
    col = np.where(leaves[..., None], np.array([0.35, 0.22, 0.06]), col)
    h = 0.6 * ground + 0.3 * moss
    return nz.normalize01(h), col


def m_mossstone(size, seed, rgb, scale):
    h, col = m_stone(size, seed, rgb, scale)
    patch = nz.normalize01(nz.fbm_perlin(size, 6, octaves=4, seed=_nseed(seed, "msp")))
    moss = np.clip((patch - 0.55) * 4, 0, 1) * (1 - h * 0.5)
    green = np.array([0.15, 0.28, 0.07])
    col = col * (1 - moss[..., None]) + green[None, None, :] * moss[..., None]
    return h, col


def m_planks(size, seed, rgb, scale):
    rows = {"small": 12, "medium": 8, "large": 6}[scale]
    yv, xv = np.indices((size, size), dtype=np.float32)
    ph = size / rows
    row = (yv // ph).astype(int)
    rng = _rng(seed, "planks")
    shift = rng.uniform(0, size, rows).astype(np.float32)[row % rows]
    length = size / rng.choice([1, 2, 2, 3])
    xs = (xv + shift) % size
    ly = yv % ph
    gap = (ly < 3) | ((xs % length) < 3)
    grain = nz.normalize01(nz.generate_perlin_noise_2d(size, (64, 4), seed=_nseed(seed, "pgrain")))
    rings = nz.normalize01(np.sin((grain * 18 + yv / ph * 3)) * 0.5 + 0.5)
    shade = rng.uniform(-0.15, 0.15, rows).astype(np.float32)[row % rows]
    h = np.where(gap, 0.1, 0.55 + 0.1 * rings)
    col = _tint(rgb, 0.6 * grain + 0.4 * rings, 0.4) * (1 + shade[..., None])
    col = np.where(gap[..., None], col * 0.35, col)
    nail = (np.hypot((xs % length) - 10, ly - ph / 2) < 3) | (np.hypot((xs % length) - (length - 10), ly - ph / 2) < 3)
    col = np.where(nail[..., None], np.array([0.25, 0.25, 0.27]), col)
    return nz.normalize01(h), col


def m_cobble(size, seed, rgb, scale):
    cells = {"small": 18, "medium": 12, "large": 8}[scale]
    f1, f2 = nz.generate_voronoi_f1_f2(size, cells, _nseed(seed, "cob"), warp_strength=0.08)
    edge = nz.normalize01(f2 - f1)
    dome = np.clip(edge * 3, 0, 1) ** 0.6
    joint = edge < 0.08
    rough = nz.normalize01(nz.fbm_perlin(size, 32, octaves=3, seed=_nseed(seed, "cr")))
    h = np.where(joint, 0.05, 0.25 + 0.6 * dome) + (rough - 0.5) * 0.08
    shade = nz.normalize01(nz.generate_voronoi_f1_f2(size, cells, _nseed(seed, "cob"), warp_strength=0.08)[0])
    col = _tint(rgb, rough, 0.3) * (0.85 + 0.3 * (1 - shade[..., None]))
    col = np.where(joint[..., None], col * 0.35, col)
    return nz.normalize01(h), col


def m_asphalt(size, seed, rgb, scale):
    grit = _rng(seed, "grit").random((size, size)).astype(np.float32)
    base = nz.normalize01(nz.fbm_perlin(size, 8, octaves=4, seed=_nseed(seed, "asph")))
    cracks = nz.voronoi_edge_lines(size, 4, _nseed(seed, "acr"), 0.4, 16)
    grey = np.array([0.22, 0.22, 0.23]) * 0.7 + np.array(rgb) * 0.3
    col = grey[None, None, :] * (0.75 + 0.35 * base[..., None] + 0.15 * (grit[..., None] - 0.5))
    col = col * (1 - 0.5 * cracks[..., None])
    h = 0.5 + 0.1 * grit - 0.3 * cracks
    return nz.normalize01(h), col


def m_facade(size, seed, rgb, scale):
    n = {"small": 8, "medium": 6, "large": 4}[scale]
    xv, yv, cw, ch = _grid(size, n, n)
    lx, ly = xv % cw, yv % ch
    win = (lx > cw * 0.2) & (lx < cw * 0.8) & (ly > ch * 0.2) & (ly < ch * 0.75)
    frame = (lx > cw * 0.16) & (lx < cw * 0.84) & (ly > ch * 0.16) & (ly < ch * 0.79) & ~win
    rng = _rng(seed, "lit")
    lit = rng.random((n, n)) > 0.7
    lit_at = lit[(xv // cw).astype(int) % n, (yv // ch).astype(int) % n]
    wall_h, wall_col = m_concrete(size, seed, rgb, "large")
    glass = np.where(lit_at[..., None], np.array([0.62, 0.50, 0.24]), np.array([0.05, 0.07, 0.10]))
    col = np.where(win[..., None], glass, np.where(frame[..., None], wall_col * 0.6, wall_col))
    h = np.where(win, 0.15, np.where(frame, 0.75, wall_h * 0.5 + 0.3))
    return nz.normalize01(h), col


def m_markings(size, seed, rgb, scale):
    h, col = m_asphalt(size, seed, rgb, scale)
    yv, xv = np.indices((size, size), dtype=np.float32)
    band = np.abs(yv - size / 2) < size / 40
    dash = (xv % (size / 4)) < size / 8
    line = band & dash
    edge = (np.abs(yv - size * 0.12) < size / 80) | (np.abs(yv - size * 0.88) < size / 80)
    paint = np.array([0.62, 0.48, 0.08])
    col = np.where(line[..., None], paint, np.where(edge[..., None], np.array([0.55, 0.55, 0.52]), col))
    return h, col


def m_crater(size, seed, rgb, scale):
    base = nz.normalize01(nz.fbm_perlin(size, 6, octaves=5, seed=_nseed(seed, "crb")))
    h = base * 0.5
    rng = _rng(seed, "craters")
    for _ in range({"small": 26, "medium": 16, "large": 9}[scale]):
        r = rng.uniform(size / 40, size / 9)
        d = _wrap_disc(size, rng.uniform(0, size), rng.uniform(0, size), r)
        bowl = np.where(d < 1, -(1 - d ** 2) * 0.5, 0)
        rim = np.exp(-((d - 1) ** 2) / 0.02) * 0.25
        h = h + bowl + rim
    col = _tint(rgb, nz.normalize01(h), 0.45)
    return nz.normalize01(h), col


def m_crystal(size, seed, rgb, scale):
    cells = {"small": 14, "medium": 9, "large": 6}[scale]
    f1, f2 = nz.generate_voronoi_f1_f2(size, cells, _nseed(seed, "cry"), warp_strength=0.0)
    edge = nz.normalize01(f2 - f1)
    facet = nz.normalize01(f1)
    rng = _rng(seed, "cryshade")
    tilt = nz.normalize01(nz.generate_perlin_noise_2d(size, cells, seed=_nseed(seed, "tilt")))
    h = 0.4 + 0.5 * (1 - facet) * 0.6 + 0.2 * tilt
    bright = np.clip(1 - edge * 12, 0, 1)
    col = np.clip(np.array(rgb)[None, None, :] * (0.7 + 0.8 * tilt[..., None]) + bright[..., None] * 0.35, 0, 1)
    return nz.normalize01(h), col


def m_alien(size, seed, rgb, scale):
    cells = {"small": 10, "medium": 6, "large": 4}[scale]
    veins = nz.normalize01(nz.layered_caustic_network(size, cells, cells * 2, 0.4, 10, _nseed(seed, "veins")))
    flesh = nz.normalize01(nz.fbm_perlin(size, 8, octaves=5, seed=_nseed(seed, "flesh")))
    v = np.clip((veins - 0.5) * 2.5, 0, 1)
    glow = np.array([0.30, 0.75, 0.55])
    col = _tint(rgb, flesh, 0.4) * (1 - v[..., None]) + glow[None, None, :] * v[..., None]
    h = 0.6 * flesh + 0.3 * v
    return nz.normalize01(h), col


def m_runes(size, seed, rgb, scale):
    h, col = _trim(size, seed, rgb, "trim_bands")
    img = Image.new("L", (size, size), 0)
    dr = ImageDraw.Draw(img)
    rng = _rng(seed, "runes")
    bands, step = 4, size / 16
    for b in range(bands):
        y0 = b * size / bands + size / bands * 0.3
        y1 = y0 + size / bands * 0.4
        for i in range(16):
            x0 = i * step + step * 0.2
            x1 = x0 + step * 0.6
            for _ in range(3):
                pts = [(x0 + rng.uniform(0, 1) * (x1 - x0), y0 + rng.uniform(0, 1) * (y1 - y0)) for _ in range(2)]
                dr.line(pts, fill=255, width=max(2, size // 160))
    carved = np.asarray(img, dtype=np.float32) / 255.0
    h = np.clip(h - carved * 0.4, 0, 1)
    col = col * (1 - 0.55 * carved[..., None])
    return nz.normalize01(h), col


def m_gold(size, seed, rgb, scale):
    yv, xv = np.indices((size, size), dtype=np.float32)
    bands = 4
    bh = size / bands
    ly = yv % bh
    step = size / 8
    d = np.hypot((xv % step) - step / 2, ly - bh / 2) / (bh * 0.32)
    ring = np.exp(-((d - 1) ** 2) / 0.03)
    dot = d < 0.35
    edge = np.minimum(ly, bh - ly) < bh * 0.12
    h = 0.3 + 0.5 * ring + 0.4 * dot + 0.3 * edge
    gold = np.array([0.62, 0.46, 0.14])
    grain = _metal(size, seed, "gold")
    base = _tint(rgb, grain, 0.2) * 0.6
    metal = gold[None, None, :] * (0.7 + 0.4 * grain[..., None])
    on = np.clip(ring + dot + edge, 0, 1)
    col = base * (1 - on[..., None]) + metal * on[..., None]
    return nz.normalize01(h), col


def m_sand(size, seed, rgb, scale):
    warp = nz.generate_perlin_noise_2d(size, 4, seed=_nseed(seed, "sw")) * 18
    yv, xv = np.indices((size, size), dtype=np.float32)
    k = {"small": 32, "medium": 22, "large": 14}[scale]
    rip = 0.5 + 0.5 * np.sin((yv + warp) / size * 2 * np.pi * k)
    dune = nz.normalize01(nz.fbm_perlin(size, 3, octaves=4, seed=_nseed(seed, "dune")))
    grain = _rng(seed, "sgrain").random((size, size)).astype(np.float32)
    h = 0.55 * dune + 0.3 * rip + 0.05 * grain
    col = _tint(rgb, h, 0.3) * (0.95 + 0.1 * grain[..., None])
    return nz.normalize01(h), col


def m_sandstone(size, seed, rgb, scale):
    h, col = m_brick(size, seed, rgb, "large" if scale != "small" else "medium")
    strata = nz.normalize01(nz.generate_perlin_noise_2d(size, (2, 32), seed=_nseed(seed, "strata")))
    col = col * (0.85 + 0.3 * strata[..., None])
    return h, col


def m_lavarock(size, seed, rgb, scale):
    h, col = m_rock(size, seed, (0.12, 0.08, 0.07), scale)
    cracks = nz.voronoi_edge_lines(size, {"small": 9, "medium": 6, "large": 4}[scale], _nseed(seed, "lava"), 0.35, 8)
    hot = np.clip(cracks * 1.4, 0, 1)
    glow = np.array([0.95, 0.38, 0.05]) * (0.6 + 0.4 * np.mean(rgb) / 0.4)
    col = col * (1 - hot[..., None]) + np.clip(glow, 0, 1)[None, None, :] * hot[..., None]
    return nz.normalize01(h - hot * 0.3), col


MATERIALS = {"panel": m_panel, "rivets": m_rivets, "grate": m_grate, "tiles": m_tiles, "brick": m_brick,
             "stone": m_stone, "concrete": m_concrete, "rock": m_rock,
             "trim_rivets": lambda s, sd, rgb, sc: _trim(s, sd, rgb, "trim_rivets"),
             "trim_bands": lambda s, sd, rgb, sc: _trim(s, sd, rgb, "trim_bands"),
             "trim_hazard": lambda s, sd, rgb, sc: _trim(s, sd, rgb, "trim_hazard"),
             "snow": m_snow, "ice": m_ice, "snowstone": m_snowstone, "bark": m_bark, "moss": m_moss,
             "mossstone": m_mossstone, "planks": m_planks, "cobble": m_cobble, "asphalt": m_asphalt,
             "facade": m_facade, "markings": m_markings, "crater": m_crater, "crystal": m_crystal, "alien": m_alien,
             "runes": m_runes, "gold": m_gold, "sand": m_sand, "sandstone": m_sandstone, "lavarock": m_lavarock}


def base_colour(seed: int, colour: str, k: int, theme: str = "") -> tuple:
    """The role's base colour: the asked hue with a little drift per texture, as dark as people's textures; a theme of
    its own world (snow, forest …) its own colours when none is asked."""
    rng = _rng(seed, f"col{k}")
    if theme in THEME_HUES:
        hue, sat, val = THEME_HUES[theme][k % len(THEME_HUES[theme])]
        if colour != "auto" and colour in HUES:
            # brief 22 D4 (Fable 06.11): a colour asked of a world theme turns its hue and half its saturation - its
            # brightness stays the theme's (snow «cold» came out lum 38 against 73 at «auto»: grey slush)
            hue = HUES[colour][0]
            sat = (sat + HUES[colour][1]) / 2
        hue = (hue + rng.uniform(-0.025, 0.025)) % 1.0
        sat = float(np.clip(sat + rng.uniform(-0.06, 0.06), 0.03, 0.9))
        val = float(np.clip(val + rng.uniform(-0.04, 0.04), 0.2, 0.7))
        return colorsys.hsv_to_rgb(hue, sat, val)
    if colour == "auto":
        colour = ["warm", "cold", "green", "rust", "warm", "grey"][int(_rng(seed, "auto").integers(0, 6))]
    hue, sat = HUES[colour]
    hue = (hue + rng.uniform(-0.04, 0.04)) % 1.0
    sat = float(np.clip(sat + rng.uniform(-0.08, 0.08), 0.05, 0.85))
    val = float(rng.uniform(0.30, 0.42))
    return colorsys.hsv_to_rgb(hue, sat, val)


def make(material: str, seed: int, colour: str, wear: str, scale: str, relief: str, k: int = 0,
         theme: str = "") -> Image.Image:
    rgb = base_colour(seed, colour, k, theme)
    h, col = MATERIALS[material](SIZE, seed + 101 * k, rgb, scale)
    grime, streak, rust = _wear_maps(SIZE, seed + 7 * k, wear)
    col = col * (1 - 0.45 * grime[..., None]) * (1 - 0.3 * streak[..., None])
    rust_rgb = np.array([0.38, 0.17, 0.07])
    col = col * (1 - rust[..., None]) + rust_rgb[None, None, :] * rust[..., None] * (0.7 + 0.3 * h[..., None])
    out = _bake(col, h, {"soft": 0.6, "medium": 1.0, "sharp": 1.6}[relief])
    return Image.fromarray((np.clip(out, 0, 1) * 255).astype(np.uint8), "RGB")


def make_set(params: dict, seed: int) -> dict:
    """The set's textures by role: {role: [(name, material, image)]}."""
    theme = theme_of(params, seed)
    colour = params.get("colour") or "auto"
    wear = params.get("wear") or "worn"
    scale = params.get("scale") or "medium"
    relief = params.get("relief") or "medium"
    rec = RECIPES[theme]
    out = {}
    k = 0
    for role, n in (("wall", 4), ("floor", 3), ("ceil", 3), ("detail", 4)):
        mats = list(rec[role])
        rng = _rng(seed, role)
        rng.shuffle(mats)
        out[role] = []
        for i in range(n):
            mat = mats[i % len(mats)]
            # the floors and the details a step darker or lighter than the walls, so the roles read apart
            out[role].append((f"{role}{i + 1}", mat, make(mat, seed, colour, wear, scale, relief, k, theme)))
            k += 1
    tread = THEME_TREAD.get(theme, "grate")
    out["tread"] = [("tread1", tread, make(tread, seed, colour, wear, "small", relief, k, theme))]
    return out


def theme_of(params: dict, seed: int) -> str:
    """The theme a set takes: the asked one, else one by the set's number."""
    return params.get("theme") if params.get("theme") in RECIPES else THEMES[seed % len(THEMES)]


def set_key(params: dict, seed: int) -> str:
    key = json.dumps({k: params.get(k) for k in ("theme", "colour", "wear", "scale", "relief")}, sort_keys=True)
    return "g" + hashlib.sha256(f"{seed}:{key}:{VERSION}".encode()).hexdigest()[:8]


def install_set(game: Path, params: dict, seed: int) -> tuple[str, dict]:
    """The set into the game's textures/mapgen_gen/<key>/ (.wal 256 in its palette, .jpg 512); made once per key.
    Returns (key, {role: [texture names]})."""
    import mapgen_textures as tx
    key = set_key(params, seed)
    d = Path(game) / "textures" / "mapgen_gen" / key
    names_file = d / "set.json"
    if names_file.is_file():
        return key, json.loads(names_file.read_text(encoding="utf-8"))["roles"]
    d.mkdir(parents=True, exist_ok=True)
    pal = tx.palette(Path(game))
    roles = {}
    for role, items in make_set(params, seed).items():
        roles[role] = []
        for name, mat, im in items:
            tex = f"mapgen_gen/{key}/{name}"
            im.convert("RGB").save(d / f"{name}.jpg", quality=90)
            small = im.resize((256, 256), Image.LANCZOS)
            (d / f"{name}.wal").write_bytes(tx.wal_bytes(small, pal, tex))
            roles[role].append(tex)
    names_file.write_text(json.dumps({"params": params, "seed": seed, "roles": roles}, ensure_ascii=False, indent=1),
                          encoding="utf-8")
    return key, roles


# ---- brief 26: the fixtures' textures - a jump pad's disc and arrows, a teleporter's portal and glow ----------------
# The PO 06.11 (q2_q3dm17's pads and portals: «не просто кружочки … анимированное направление … красиво, эффектно,
# мощно»): its textures are id's (sfx/*, grieve/*, loose in his game only) - ours are drawn here, in the light's colour of
# the map's style. Each is 64 x 64 in the game's units (the .wal; a disc of 56 shows its ring whole) and 256 drawn
# (.jpg, what q2pro shows); the arrows point along +s (image right) - the builder turns s along the flight, and the
# engine's FLOWING scroll moves a texture towards +s.
FX_VERSION = 1
FX_WAL = 64
FX_JPG = 256
FX_NAMES = ("padring", "padarrow", "flowarrow", "portal", "glow")


def _fx_canvas(k=4):
    s = FX_JPG * k
    return Image.new("RGB", (s, s), (0, 0, 0)), s


def _fx_done(im: Image.Image) -> Image.Image:
    return im.resize((FX_JPG, FX_JPG), Image.LANCZOS)


def _fx_col(rgb, v=1.0):
    return tuple(int(max(0, min(255, c * 255 * v))) for c in rgb)


def fx_padring(rgb) -> Image.Image:
    """A vertical pad's disc: dark plate, a bright rim, an inner ring, spokes, a dark centre with three marks."""
    im, s = _fx_canvas()
    d = ImageDraw.Draw(im)
    c = s / 2
    d.rectangle((0, 0, s, s), fill=(26, 28, 32))
    for r, w, v in ((0.47, 0.035, 1.0), (0.42, 0.012, 0.55), (0.31, 0.022, 0.85), (0.20, 0.010, 0.45)):
        R = r * s
        d.ellipse((c - R, c - R, c + R, c + R), outline=_fx_col(rgb, v), width=max(1, int(w * s)))
    for k in range(12):
        a = k * math.pi / 6
        d.line((c + 0.22 * s * math.cos(a), c + 0.22 * s * math.sin(a), c + 0.29 * s * math.cos(a),
                c + 0.29 * s * math.sin(a)), fill=_fx_col(rgb, 0.6), width=int(0.008 * s))
    R = 0.18 * s
    d.ellipse((c - R, c - R, c + R, c + R), fill=(14, 15, 18))
    for k in range(3):
        a = -math.pi / 2 + k * 2 * math.pi / 3
        x, y = c + 0.09 * s * math.cos(a), c + 0.09 * s * math.sin(a)
        d.ellipse((x - 0.025 * s, y - 0.025 * s, x + 0.025 * s, y + 0.025 * s), fill=_fx_col(rgb, 0.9))
    return _fx_done(im)


def _chevrons(d, s, rgb, v, period, thick, bg=None):
    """Chevrons pointing to +x (image right), `period` apart, across the whole height."""
    c = s / 2
    for k in range(-1, int(s / period) + 2):
        x0 = k * period
        tip = (x0 + period * 0.55, c)
        d.line((x0, c - s * 0.36, tip[0], tip[1]), fill=_fx_col(rgb, v), width=thick)
        d.line((x0, c + s * 0.36, tip[0], tip[1]), fill=_fx_col(rgb, v), width=thick)


def fx_padarrow(rgb) -> Image.Image:
    """A slanted pad's top: dark plate with rails and three bright chevrons pointing along +s."""
    im, s = _fx_canvas()
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, s, s), fill=(30, 32, 36))
    d.rectangle((0, 0, s, s * 0.06), fill=_fx_col(rgb, 0.45))
    d.rectangle((0, s * 0.94, s, s), fill=_fx_col(rgb, 0.45))
    _chevrons(d, s, rgb, 1.0, s // 4, int(s * 0.05))     # a whole number of periods: the texture tiles
    return _fx_done(im)


def fx_flowarrow(rgb) -> Image.Image:
    """The sheet over a slanted pad (drawn translucent, scrolling): chevrons on black."""
    im, s = _fx_canvas()
    d = ImageDraw.Draw(im)
    _chevrons(d, s, rgb, 1.0, s // 2, int(s * 0.07))
    return _fx_done(im)


def fx_portal(rgb) -> Image.Image:
    """A teleporter's portal sheet (translucent, scrolling up once turned): streaks along s on a deep field."""
    rng = np.random.default_rng(int(hashlib.sha256(repr(rgb).encode()).hexdigest()[:8], 16))
    s = FX_JPG
    base = np.zeros((s, s, 3), np.float32)
    col = np.array(rgb, np.float32)
    deep = col * 0.18 + np.array([0.02, 0.03, 0.08], np.float32)
    base[:] = deep
    for _ in range(140):
        y = int(rng.integers(0, s))
        x0 = int(rng.integers(0, s))
        ln = int(rng.integers(s // 8, s // 2))
        v = float(rng.uniform(0.35, 1.0))
        th = int(rng.integers(1, 3))
        xs = (np.arange(ln) + x0) % s
        fade = np.sin(np.linspace(0, math.pi, ln))[:, None] * v
        for dy in range(th):
            base[(y + dy) % s, xs] = np.maximum(base[(y + dy) % s, xs], col[None, :] * fade)
    for _ in range(90):
        y, x = int(rng.integers(0, s)), int(rng.integers(0, s))
        base[y, x] = np.maximum(base[y, x], np.array([1.0, 1.0, 1.0]) * float(rng.uniform(0.6, 1.0)))
    return Image.fromarray((np.clip(base, 0, 1) * 255).astype(np.uint8), "RGB")


def fx_glow(rgb) -> Image.Image:
    """A glow strip: the light's colour, bright, a soft band along s."""
    s = FX_JPG
    t = np.linspace(-1, 1, s)[:, None]
    v = 0.86 + 0.14 * np.cos(t * math.pi / 2)
    hi = np.array(rgb, np.float32) * 0.5 + 0.5
    out = np.clip(hi[None, None, :] * v[..., None] * np.ones((s, s, 1), np.float32), 0, 1)
    return Image.fromarray((out * 255).astype(np.uint8), "RGB")


FX_MAKERS = {"padring": fx_padring, "padarrow": fx_padarrow, "flowarrow": fx_flowarrow, "portal": fx_portal,
             "glow": fx_glow}


def fx_key(rgb) -> str:
    return "fx" + hashlib.sha256(f"{[round(c, 2) for c in rgb]}:{FX_VERSION}".encode()).hexdigest()[:6]


def install_fixtures(game: Path, rgb) -> dict:
    """The fixtures' five textures into the game's textures/mapgen_gen/<fx key>/ (made once per colour), as
    {name: texture path} - a path of 31 characters at most (the BSP's texinfo name)."""
    import mapgen_textures as tx
    rgb = tuple(float(c) for c in rgb)
    key = fx_key(rgb)
    d = Path(game) / "textures" / "mapgen_gen" / key
    names = {n: f"mapgen_gen/{key}/{n}" for n in FX_NAMES}
    if all((d / f"{n}.wal").is_file() and (d / f"{n}.jpg").is_file() for n in FX_NAMES):
        return names
    d.mkdir(parents=True, exist_ok=True)
    pal = tx.palette(Path(game))
    for n in FX_NAMES:
        im = FX_MAKERS[n](rgb)
        im.save(d / f"{n}.jpg", quality=92)
        (d / f"{n}.wal").write_bytes(tx.wal_bytes(im.resize((FX_WAL, FX_WAL), Image.LANCZOS), pal, names[n]))
    return names


def sheet(sets: dict, path: Path) -> None:
    tiles = [(role, name, im) for role, items in sets.items() for name, _m, im in items]
    cols = 5
    rows = -(-len(tiles) // cols)
    s = 200
    out = Image.new("RGB", (cols * s, rows * (s + 18)), (20, 20, 22))
    dr = ImageDraw.Draw(out)
    for i, (role, name, im) in enumerate(tiles):
        x, y = (i % cols) * s, (i // cols) * (s + 18)
        out.paste(im.resize((s, s)), (x, y))
        dr.text((x + 4, y + s + 2), name, fill=(220, 220, 220))
    out.save(path, quality=88)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("--theme", choices=THEMES)
    ap.add_argument("--colour", choices=COLOURS, default="auto")
    ap.add_argument("--wear", choices=WEARS, default="worn")
    ap.add_argument("--scale", choices=SCALES, default="medium")
    ap.add_argument("--relief", choices=RELIEFS, default="medium")
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    params = {"theme": a.theme, "colour": a.colour, "wear": a.wear, "scale": a.scale, "relief": a.relief}
    sets = make_set(params, a.seed)
    sheet(sets, a.out / f"sheet_{a.theme or 'auto'}_{a.seed}.jpg")
    print(a.out / f"sheet_{a.theme or 'auto'}_{a.seed}.jpg")
    return 0


if __name__ == "__main__":
    sys.exit(main())
