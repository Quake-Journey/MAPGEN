r"""Brief 26 D1: the fixtures' five textures (mapgen_texgen.install_fixtures) - each a .wal of 64 with four mips in the
game's palette and a .jpg of 256, all five different, every texture path inside the BSP's 31 characters; the arrows
point along +s (the builder turns s along the flight and the engine's FLOWING scroll moves a texture to +s); the glow is
bright (luminance >= 200), the portal deep (mean <= 120). Two colours: the neutral one and a generated set's (hell).

RED (in the run): the arrow test on the arrows mirrored must FAIL - it sees the direction, not just bright pixels.

    python tools/check_mapgen_fixture_textures.py
"""
from __future__ import annotations

import shutil
import struct
import sys
from pathlib import Path

import numpy as np
from PIL import Image

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import mapgen_load_guard  # noqa: E402
import mapgen_texgen as tg  # noqa: E402
import mapgen_textures as tx  # noqa: E402

GAME = Path(r"O:\Claude2\q2pro-release\baseq2")
WORK = Path(r"O:\Claude2\_agent_temp\claude\fixture_textures")
FAILED = 0


def row(ok: bool, what: str, said: str = "") -> None:
    global FAILED
    FAILED += 0 if ok else 1
    print(f"{'PASS' if ok else 'FAIL'} {what}" + (f" -- {said}" if said else ""))


def points_plus_s(im: Image.Image, period: int) -> float:
    """Chevrons «>»: in each period the bright pixels lie further along +x the nearer they are to the middle row - the
    correlation of (x mod period) with |y - middle| is strongly negative. Returns that correlation."""
    a = np.asarray(im.convert("L"), np.float32)
    ys, xs = np.nonzero(a > 0.6 * a.max())
    mid = a.shape[0] / 2
    xm = xs % period
    keep = (xm > period * 0.05) & (xm < period * 0.95)
    return float(np.corrcoef(xm[keep], np.abs(ys[keep] - mid))[0, 1])


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    mapgen_load_guard.pin_self()
    shutil.rmtree(WORK, ignore_errors=True)
    (WORK / "pics").mkdir(parents=True)
    # a game of its own: the palette only (the real game is the Studio's client, written on a generation)
    (WORK / "pics" / "colormap.pcx").write_bytes(tx.game_file(GAME, "pics/colormap.pcx"))
    for label, rgb in (("neutral", (0.72, 0.84, 1.0)), ("hell", tg.THEME_LIGHT["hell"])):
        names = tg.install_fixtures(WORK, rgb)
        d = WORK / "textures" / "mapgen_gen" / tg.fx_key(rgb)
        hashes = set()
        whole = True
        for n in tg.FX_NAMES:
            w, j = d / f"{n}.wal", d / f"{n}.jpg"
            if not (w.is_file() and j.is_file()):
                whole = False
                continue
            b = w.read_bytes()
            ww, hh = struct.unpack("<II", b[32:40])
            offs = struct.unpack("<4I", b[40:56])
            whole &= ww == tg.FX_WAL and hh == tg.FX_WAL and offs[0] == 100 and len(b) == 100 + sum((64 >> k) ** 2 for k in range(4))
            whole &= Image.open(j).size == (tg.FX_JPG, tg.FX_JPG)
            hashes.add(hash(b))
        row(whole and len(hashes) == len(tg.FX_NAMES), f"{label}: five textures, .wal 64 with four mips and .jpg 256, all different",
            f"{len(hashes)} distinct")
        longest = max(len(p) for p in names.values())
        row(longest <= 31, f"{label}: texture paths fit the BSP's name (31)", str(longest))
        arrow = Image.open(d / "padarrow.jpg")
        flow = Image.open(d / "flowarrow.jpg")
        ca, cf = points_plus_s(arrow, tg.FX_JPG // 4), points_plus_s(flow, tg.FX_JPG // 2)
        row(ca < -0.5 and cf < -0.5, f"{label}: the arrows point along +s", f"correlation {ca:.2f}, {cf:.2f}")
        red = points_plus_s(arrow.transpose(Image.FLIP_LEFT_RIGHT), tg.FX_JPG // 4)
        row(red > 0.5, f"{label}: RED - the arrows mirrored read as pointing back", f"correlation {red:.2f}")
        lum = lambda p: float(np.asarray(Image.open(p).convert("L"), np.float32).mean())  # noqa: E731
        g, pt = lum(d / "glow.jpg"), lum(d / "portal.jpg")
        row(g >= 200 and pt <= 120, f"{label}: the glow bright, the portal deep", f"glow {g:.0f}, portal {pt:.0f}")
    shutil.rmtree(WORK, ignore_errors=True)
    print("PASS" if not FAILED else f"FAIL ({FAILED})")
    return 0 if not FAILED else 1


if __name__ == "__main__":
    sys.exit(main())
