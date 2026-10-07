"""A face this generator invents has to be able to WEAR its texture.

A Quake II surface maps texture coordinates as s = p.u + su, t = p.v + sv:
a projection of the face along (u x v). The two axes must span the face. If
either of them is parallel to the face's own normal the projection is edge-on
- s or t is constant across the whole surface, one column of texels is pulled
along it, and the map draws a streak. The PO photographed exactly that on
2026-09-10, on every map with a hollow in it, and asked why it looked as if
somebody had cut it with a knife.

    python tools/check_mapgen_texture_axes.py [--map MAP.bsp ...]
                                              [--work DIR] [--floor F]

The measure, per DRAWN face of a compiled BSP (SKY and NODRAW are not drawn
and are skipped):

    span = |n . (u x v)| / |u x v|

with n the plane normal already flipped by the face's side bit. It is 1 for an
axial face wearing its own axes, 0.577 at worst for the dominant-axis rule a
level editor gives a new face, and 0 for a smear. The floor is 0.5, which
q2dm1 clears everywhere (its own minimum is 0.6).

What this guard runs, in order:

    the donor            q2dm1 as it ships, the reference: no face under the
                         floor, measured rather than quoted;
    the RED              a room this guard writes with ONE face deliberately
                         wearing its neighbour's axes, compiled - the measure
                         has to find it, or the measure is not looking;
    the hollows          the two regions the 2026-09-10 forks streaked, cut
                         into the donor by the recut driver and compiled -
                         `add_clipped` used to hand these faces the skin
                         side's mapping and swap only the normal, which put
                         88, 86 and 62 streaked faces in the three F90 forks
                         and 50 in the 93-permille map;
    every named map      `--map` judges an already-compiled artifact and
                         compiles nothing, which is how the handover gate
                         asks the question of the files it is about to
                         install.
"""
from __future__ import annotations

import argparse
import json
import struct
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CORPUS = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260831\corpus")
from mapgen_load_guard import game_dir  # noqa: E402  (brief 13 W1: the game folder of this run)
GAME = Path(game_dir())
PIN = REPO / "tools" / "mapgen_compiler_pin.json"
WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260912\texture_axes")

SURF_SKY = 0x4
SURF_NODRAW = 0x80

# The two regions the forks of 2026-09-10 came out streaked on, read off their
# compiled faces: the hole in the wall the PO called "топ", and the big room
# the graft's fit hollows on every seed.
HOLE = (1504, 1152, 1048, 1536, 1258, 1152)
ROOM = (494, 1157, 792, 882, 1431, 1056)

FLOOR = 0.5

CASES = 0
FAILED = 0


def check(name: str, ok: bool, detail: str = "") -> bool:
    global CASES, FAILED
    CASES += 1
    print(("  PASS  " if ok else "  FAIL  ") + name
          + (f"  -- {detail}" if detail else ""))
    if not ok:
        FAILED += 1
    return ok


# ---- reading a compiled map ------------------------------------------------

def lump(data: bytes, i: int) -> bytes:
    ofs, ln = struct.unpack_from("<ii", data, 8 + 8 * i)
    return data[ofs:ofs + ln]


def spans(path: Path) -> list[tuple[float, str, tuple, tuple]]:
    """Every drawn face as (span, texture, normal, centre)."""
    data = path.read_bytes()
    if data[:4] != b"IBSP" or struct.unpack_from("<i", data, 4)[0] != 38:
        raise SystemExit(f"{path} is not a Quake II BSP")
    raw = lump(data, 1)
    planes = [struct.unpack_from("<ffffi", raw, 20 * i)
              for i in range(len(raw) // 20)]
    raw = lump(data, 2)
    verts = [struct.unpack_from("<fff", raw, 12 * i)
             for i in range(len(raw) // 12)]
    raw = lump(data, 5)
    texinfo = []
    for i in range(len(raw) // 76):
        rec = struct.unpack_from("<8fii32si", raw, 76 * i)
        texinfo.append((rec[0:3], rec[4:7], rec[8],
                        rec[10].split(b"\0")[0].decode("latin1")))
    raw = lump(data, 6)
    faces = [struct.unpack_from("<HhihhBBBBi", raw, 20 * i)
             for i in range(len(raw) // 20)]
    raw = lump(data, 11)
    edges = [struct.unpack_from("<HH", raw, 4 * i)
             for i in range(len(raw) // 4)]
    raw = lump(data, 12)
    surfedges = [struct.unpack_from("<i", raw, 4 * i)[0]
                 for i in range(len(raw) // 4)]

    out = []
    for planenum, side, firstedge, numedges, tex in \
            ((f[0], f[1], f[2], f[3], f[4]) for f in faces):
        u, v, flags, name = texinfo[tex]
        if flags & (SURF_SKY | SURF_NODRAW):
            continue
        n = planes[planenum][0:3]
        if side:
            n = (-n[0], -n[1], -n[2])
        w = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2],
             u[0] * v[1] - u[1] * v[0])
        wl = (w[0] ** 2 + w[1] ** 2 + w[2] ** 2) ** 0.5
        span = 0.0 if wl < 1e-9 else \
            abs(n[0] * w[0] + n[1] * w[1] + n[2] * w[2]) / wl
        pts = []
        for e in range(numedges):
            se = surfedges[firstedge + e]
            pts.append(verts[edges[abs(se)][1 if se < 0 else 0]])
        centre = tuple(sum(p[a] for p in pts) / len(pts) for a in range(3))
        out.append((span, name, n, centre))
    return out


def judge(what: str, path: Path, floor: float, expect_smeared: bool = False,
          show: int = 6) -> int:
    if not path.is_file():
        check(f"{what} is there to be measured", False, str(path))
        return -1
    faces = spans(path)
    bad = [f for f in faces if f[0] < floor]
    detail = f"{len(faces)} drawn faces, {len(bad)} under {floor}"
    if bad:
        worst = sorted(bad)[:show]
        detail += "; " + "; ".join(
            f"{t} at ({c[0]:.0f} {c[1]:.0f} {c[2]:.0f}) span {s:.2f}"
            for s, t, _n, c in worst)
    if expect_smeared:
        check(f"{what} draws the streak the measure is looking for - the RED",
              bool(bad), detail)
    else:
        check(f"{what} wears its textures on every drawn face", not bad,
              detail)
    return len(bad)


# ---- the fixtures ----------------------------------------------------------

def pinned() -> tuple[Path, str]:
    """The pinned compiler, or another binary the pin's own list says a
    complete M0Q passed (`tools/mapgen_pinned_compiler.py`)."""
    from mapgen_pinned_compiler import pinned_compiler
    return pinned_compiler()


def compile_map(path: Path) -> None:
    exe, threads = pinned()
    load_guard.run(
        [str(exe), "-bsp", "-threads", threads, "-moddir", str(GAME),
         "-basedir", str(GAME), "-gamedir", str(GAME), str(path)],
        capture_output=True, text=True, timeout=3600)


AXES = "[ 1 0 0 0 ] [ 0 0 -1 0 ] 0 1 1 1 0 0"
# The defect, spelled: a mapping whose S axis runs along +y and whose T axis
# runs down -z. On a wall facing x that is correct and is what q2dm1 uses; on
# a FLOOR it is edge-on, and the floor draws one column of texels smeared the
# length of the room. This is `add_clipped`'s old behaviour written by hand.
INHERITED = "[ 0 1 0 0 ] [ 0 0 -1 0 ] 0 1 1 1 0 0"
SKY_AXES = "[ 1 0 0 0 ] [ 0 0 -1 0 ] 0 1 1 1 4 0"


def box(x0, y0, z0, x1, y1, z1, tex, axes=AXES,
        floor_axes: str | None = None) -> str:
    faces = [
        ([(x0, 0, 0), (x0, 1, 0), (x0, 0, 1)], axes),
        ([(x1, 0, 0), (x1, 0, 1), (x1, 1, 0)], axes),
        ([(0, y0, 0), (0, y0, 1), (1, y0, 0)], axes),
        ([(0, y1, 0), (1, y1, 0), (0, y1, 1)], axes),
        ([(0, 0, z0), (1, 0, z0), (0, 1, z0)], axes),
        ([(0, 0, z1), (0, 1, z1), (1, 0, z1)], floor_axes or axes),
    ]
    out = ["{"]
    for pts, ax in faces:
        out.append(" ".join(f"( {p[0]} {p[1]} {p[2]} )" for p in pts)
                   + f" {tex} {ax}")
    out.append("}")
    return "\n".join(out)


def write_red(path: Path) -> None:
    """One sealed room whose FLOOR wears the wall's axes."""
    t, lo, hi, lid = 32, 0, 768, 512
    brushes = [
        # the floor slab: its +z face - the one the player sees - is given the
        # x-facing wall's mapping, which is the bug
        box(lo, lo, lo - t, hi, hi, lo, "e2u3/floor1_6",
            floor_axes=INHERITED),
        box(lo - t, lo, lo, lo, hi, lid, "e2u3/blum12_1"),
        box(hi, lo, lo, hi + t, hi, lid, "e2u3/blum12_1"),
        box(lo - t, lo - t, lo, hi + t, lo, lid, "e2u3/blum12_1"),
        box(lo - t, hi, lo, hi + t, hi + t, lid, "e2u3/blum12_1"),
        box(lo - t, lo - t, lid, hi + t, hi + t, lid + t, "e2u3/sky1",
            SKY_AXES),
    ]
    text = ["// Game: Quake 2", "// Format: Valve",
            "{", '"classname" "worldspawn"', '"mapversion" "220"',
            "\n".join(brushes), "}",
            "{", '"classname" "info_player_start"',
            '"origin" "128 128 32"', "}",
            "{", '"classname" "light"', '"origin" "384 384 400"',
            '"light" "500"', "}"]
    path.write_text("\n".join(text) + "\n", encoding="ascii")


# How the recut driver is built is `check_mapgen_recut.py`'s answer, and there
# is no second answer: a copied source list drifts the day a module is added,
# and the failure it gives is a linker error inside an unrelated guard.
sys.path.insert(0, str(REPO / "tools"))
from check_mapgen_recut import build_driver          # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mapgen_load_guard as load_guard          # noqa: E402


def hollow(exe: Path, donor: Path, region: tuple, out: Path) -> Path:
    load_guard.run([str(exe), str(donor), "--seed", "1", "--hollow",
                    *[str(v) for v in region], "--out", str(out)],
                   capture_output=True, text=True, timeout=3600)
    compile_map(out)
    return out.with_suffix(".bsp")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--map", type=Path, action="append", default=[])
    ap.add_argument("--work", type=Path, default=WORK)
    ap.add_argument("--floor", type=float, default=FLOOR)
    ap.add_argument("--donor", type=Path, default=CORPUS / "q2dm1.bsp")
    a = ap.parse_args()

    if a.map:
        print("the maps named, as they were compiled")
        for m in a.map:
            judge(m.name, m, a.floor)
        print(f"SUMMARY {CASES} cases asserted, {FAILED} failures")
        return 1 if FAILED else 0

    a.work.mkdir(parents=True, exist_ok=True)

    print("the donor, which is the reference")
    judge("q2dm1", a.donor, a.floor)

    print("the streak, written by hand and compiled - the RED")
    red = a.work / "red_inherited_axes.map"
    write_red(red)
    compile_map(red)
    judge("a floor wearing the wall's axes", red.with_suffix(".bsp"), a.floor,
          expect_smeared=True)

    print("the two regions the forks of 2026-09-10 streaked, cut fresh")
    exe = build_driver(REPO, a.work)
    for name, region in (("the hole in the wall", HOLE),
                         ("the room the fit hollows", ROOM)):
        cut = hollow(exe, a.donor, region, a.work / f"cut_{region[0]}.map")
        judge(f"{name} {region}", cut, a.floor)

    print(f"SUMMARY {CASES} cases asserted, {FAILED} failures")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
