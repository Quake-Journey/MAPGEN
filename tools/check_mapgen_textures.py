r"""The generator's texture pack (Fable's brief 11 D3, ledger row 412k) - no map needed.

A fixture pack is built by `tools/mapgen_textures.py` from six sources: two of the PO's surface pictures, two of the
fetched Poly Haven colour maps (from the sources folder - no network here), a picture made here with a photobank's
footer band and its caption (a texture under it), and one made here too small. Asserted:
* every accepted pair exists: `<name>.wal` 8-bit, 256x256 (powers of two), 4 mips of the right sizes, the name field
  `mapgen/<name>`, its colours from the game's own palette - and `<name>.jpg` 512x512 the same picture (its mean colour
  within 8/255 of the wal's);
* tileable: the step across the wrap no larger than 2.5 times a step inside;
* the footer is trimmed: no row of the accepted texture made from the banded picture is as dark as the band;
* the too-small one is refused, with its reason in the catalogue, and nothing is accepted without its source's sha256;
* every mask fades to nothing at its border (no halo, no edge can show) and the PO's crater pictures are among them;
* `install` copies the pack into a game folder; `crack` draws a mask into a game texture of the same size and palette.
RED, three: the band trimming taken out - the band reaches the texture; a 200x200 wal - the size check fails; a wal
written in a palette not the game's - the colour check fails.

    python tools/check_mapgen_textures.py [--work DIR]
"""
from __future__ import annotations

import argparse
import json
import shutil
import struct
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import mapgen_textures as tx  # noqa: E402

WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260918\textures_guard")
FAILED = TOTAL = 0


def check(name: str, ok: bool, detail: str = "") -> bool:
    global FAILED, TOTAL
    TOTAL += 1
    FAILED += 0 if ok else 1
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  -- {detail}" if detail else ""), flush=True)
    return ok


def wal_ok(path: Path, pal: list[int]) -> str:
    """'' when the .wal is a game texture of the pack: sizes, mips, name, the game's palette (its jpg's colour)."""
    d = path.read_bytes()
    name, w, h = struct.unpack_from("<32sII", d, 0)
    offs = struct.unpack_from("<4I", d, 40)
    if w & (w - 1) or h & (h - 1) or (w, h) != (tx.WAL, tx.WAL):
        return f"{w}x{h}, not {tx.WAL}x{tx.WAL}"
    for k in range(4):
        if offs[k] + (w >> k) * (h >> k) > len(d):
            return f"mip {k} past the end"
    if offs[1] != offs[0] + w * h:
        return "mips out of place"
    if name.split(b"\0")[0].decode("latin1") != "mapgen/" + path.stem:
        return f"name field {name.split(b'\0')[0]!r}"
    jpg = path.with_suffix(".jpg")
    if not jpg.is_file():
        return "no .jpg beside it"
    hi = Image.open(jpg)
    if hi.size != (tx.HI, tx.HI):
        return f".jpg {hi.size}"
    # region by region (32x32 averages): the dither's noise averages out, a wrong palette does not
    a = np.asarray(tx.wal_image(d, pal).resize((32, 32), Image.BOX)).astype(np.float32)
    b = np.asarray(hi.convert("RGB").resize((32, 32), Image.BOX)).astype(np.float32)
    err = float(np.abs(a - b).mean())
    if err > 14.0:
        return f"the wal's colours stand {err:.0f} off the picture's region by region - not the game's palette"
    return ""


def fixture(work: Path) -> list:
    floor = sorted((tx.SURFACES / "Поверхности для пола").glob("*.jpg"))
    wall = sorted((tx.SURFACES / "Поверхности для стен").glob("*.jpg"))
    web = sorted(tx.SOURCES.glob("ph_rock_*.jpg"))[:1] + sorted(tx.SOURCES.glob("ph_metal_*.jpg"))[:1]
    if len(web) < 2:
        raise SystemExit(f"no fetched sources in {tx.SOURCES}: run `mapgen_textures.py build` once")
    # a gravel picture with a photobank's footer under it: a dark band 8% high with a light caption
    base = Image.open(tx.long(floor[3])).convert("RGB").resize((1024, 768))
    dr = ImageDraw.Draw(base)
    dr.rectangle([0, 620, 1024, 768], fill=(18, 18, 18))
    for k in range(4):
        dr.text((20 + 260 * k, 640 + 30 * (k % 3)), "BIGSTOCK  Image ID: 123456789", fill=(230, 230, 230))
    banded = work / "src_banded.png"
    base.save(banded)
    small = work / "src_small.png"
    Image.new("RGB", (200, 150), (120, 100, 80)).save(small)
    return [(floor[3], "floor", None), (wall[11], "wall", None), (web[0], "web", "rock"), (web[1], "web", "metal"),
            (banded, "floor", "ground"), (small, "floor", None)]


def build(work: Path, tag: str, only: list) -> tuple[Path, dict]:
    out = work / tag
    if out.exists():
        shutil.rmtree(out)
    tx.build(out, False, tx.GAME, only=only, sheets_to=out / "sheets", catalogue_to=None)
    tex = out / "textures" / "mapgen"
    return tex, json.loads((tex / "catalogue.json").read_text(encoding="utf-8"))


def band_reached(tex: Path, cat: dict) -> float:
    """The flattest run of rows of the base made from the banded picture: the least detail in 24 rows (the mean step
    between neighbours) over the picture's median - a footer is flat but for its caption, a surface is not."""
    t = next((t for t in cat["textures"] if t["source"].endswith("src_banded.png") and t["variant"] == "base"), None)
    if not t:
        return -1.0
    a = np.asarray(Image.open(tex / (t["name"].split("/", 1)[1] + ".jpg")).convert("L")).astype(np.float32)
    detail = np.abs(np.diff(a, axis=1)).mean(axis=1)
    run = np.convolve(detail, np.ones(24) / 24, mode="valid")
    return float(run.min() / max(1e-3, np.median(detail)))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, default=WORK)
    a = ap.parse_args()
    a.work.mkdir(parents=True, exist_ok=True)
    pal = tx.palette(tx.GAME)
    only = fixture(a.work)
    tex, cat = build(a.work, "green", only)
    acc = cat["textures"]
    check("the fixture's surfaces accepted, each with its variants", len({t["base"] for t in acc}) >= 4,
          f"{len(acc)} pairs of {len({t['base'] for t in acc})} bases")
    bad = [(t["name"], why) for t in acc if (why := wal_ok(tex / (t["name"].split("/", 1)[1] + ".wal"), pal))]
    check("every pair: a 256 wal in the game's palette with 4 mips, its 512 jpg the same picture", not bad,
          "; ".join(f"{n}: {w}" for n, w in bad[:4]))
    seams = [(t["name"], t["seam"]) for t in acc if t["seam"] > 2.5]
    check("every texture tiles (the wrap's step at most 2.5 an inner one)", not seams, str(seams[:4]))
    check("every accepted texture names its source and its sha256", all(t["source"] and t["sha256"] for t in acc))
    r = band_reached(tex, cat)
    check("the photobank's footer is trimmed: no flat band left in the texture", r > 0.5, f"flattest 24 rows {r:.2f} of the body's detail")
    small = [x for x in cat["refused"] if x["source"].endswith("src_small.png")]
    check("the too-small picture is refused, its reason said", bool(small) and "too small" in small[0]["why"],
          small[0]["why"] if small else "not refused")
    masks = cat["masks"]
    halo = []
    for m in masks:
        arr = np.asarray(Image.open(tex / "masks" / f"{m['name']}.png")).astype(np.float32) / 255
        if m["kind"] == "picture" and max(arr[0].max(), arr[-1].max(), arr[:, 0].max(), arr[:, -1].max()) > 0.02:
            halo.append(m["name"])
    check("the masks: generated cracks, craters, holes, soot and the PO's pictures; a picture's fades out at its border",
          not halo and {"crack", "crater", "hole", "soot", "picture"} <= {m["kind"] for m in masks},
          f"{len(masks)} masks" + (f"; edge shows on {halo}" if halo else ""))
    game = a.work / "game"
    if game.exists():
        shutil.rmtree(game)
    (game / "textures" / "e1u1").mkdir(parents=True)
    for n in ("pics/colormap.pcx", "textures/e1u1/metal1_2.wal"):
        data = tx.game_file(tx.GAME, n)
        (game / n).parent.mkdir(parents=True, exist_ok=True)
        (game / n).write_bytes(data)
    tx.install(game, a.work / "green")
    check("install: the pack is in the game folder", (game / "textures" / "mapgen" / "catalogue.json").is_file())
    needs = a.work / "needs.txt"
    needs.write_text("mgd/fixture1 e1u1/metal1_2 crack1\n", encoding="utf-8")
    rc = tx.crack(game, needs, a.work / "green")
    made = game / "textures" / "mgd" / "fixture1.wal"
    orig = tx.game_file(tx.GAME, "textures/e1u1/metal1_2.wal")
    same = made.is_file() and struct.unpack_from("<II", made.read_bytes(), 32) == struct.unpack_from("<II", orig, 32)
    darker = made.is_file() and np.asarray(tx.wal_image(made.read_bytes(), pal)).mean() < \
        np.asarray(tx.wal_image(orig, pal)).mean()
    check("crack: a game texture with a mask drawn in, its size and palette", rc == 0 and same and darker)

    # RED 1: the band trimming taken out
    keep = tx.trim_bands
    tx.trim_bands = lambda arr: (arr, [])
    try:
        rtex, rcat = build(a.work, "red_band", only)
        rr = band_reached(rtex, rcat)
        check("RED: without trimming the band reaches the texture - the case above goes red", 0 <= rr <= 0.5,
              f"flattest 24 rows {rr:.2f}")
    finally:
        tx.trim_bands = keep
    # RED 2: a wal not a power of two
    some = tex / (acc[0]["name"].split("/", 1)[1] + ".wal")
    npot = a.work / "npot" / some.name
    npot.parent.mkdir(exist_ok=True)
    shutil.copy2(some.with_suffix(".jpg"), npot.with_suffix(".jpg"))
    npot.write_bytes(tx.wal_bytes(Image.open(some.with_suffix(".jpg")).resize((200, 200)), pal, "mapgen/" + some.stem))
    check("RED: a 200x200 wal is caught", "200x200" in wal_ok(npot, pal), wal_ok(npot, pal))
    # RED 3: a wal in another palette
    # the game's own colours in another order: every index a wrong colour (a greyscale palette was tried first and,
    # by chance, its indices fell on the game's brown ramp under a brown texture)
    order = np.random.default_rng(7).permutation(256)
    grey = [pal[3 * int(i) + c] for i in order for c in range(3)]
    other = a.work / "npal" / some.name
    other.parent.mkdir(exist_ok=True)
    shutil.copy2(some.with_suffix(".jpg"), other.with_suffix(".jpg"))
    other.write_bytes(tx.wal_bytes(Image.open(some.with_suffix(".jpg")).resize((256, 256)), grey, "mapgen/" + some.stem))
    check("RED: a wal in a palette not the game's is caught", "palette" in wal_ok(other, pal), wal_ok(other, pal)[:90])
    print(f"{TOTAL - FAILED}/{TOTAL} passed")
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
